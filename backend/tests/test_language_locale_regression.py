"""Regression tests for the "English deployment still answers in Chinese" bug.

Symptom (2026-08-09): a backend deployed/run with ``VITOOM_LOCALE=en_US``, and a
browser session that correctly negotiated ``locale=en-US``, still produced
Chinese assistant replies - including replies that leaked internal routing/
classification text verbatim (e.g. "分派原则...闲聊/说明性问题...").

Two independent hardcoded-Chinese sources fed the model's prompt regardless of
the resolved session language, and together they dominated the model's output
language even with an explicit "respond in {default_language}" instruction
elsewhere in the same prompt:

1. ``build_prompt_with_history()`` wrapped every turn in fixed Chinese section
   labels ("[历史摘要]"/"[过去对话]"/"[本轮输入]") - see
   ``backend/services/conversation/__init__.py``.
2. ``config/agents/presets/preset-master-agent.yaml``'s agent ``role``/``goal``/
   ``backstory`` and task ``description``/``expected_output`` were hardcoded
   Chinese - injected verbatim into the system prompt by
   ``AgentSpec``/``TaskSpec`` (backend/services/agent/specs/__init__.py) via
   ``_agent_system_block()`` (backend/services/agent/no_tool_runner.py).

The fix makes both locale-aware, keyed by the same language-name convention as
``backend/services/agent/tools/builtin/_fallback_strings.py``
("English"/"Chinese"/"Japanese"), and threads the session's resolved
``default_language`` into both from a single point in
``backend/services/chat/master_runtime.py``.

These tests exercise the pure resolution logic directly (no live LLM call, no
WebSocket) so they run fast and would fail if this locale-awareness regresses
or if a preset is edited back into a single hardcoded language.

Run inside the backend container, which has this project's real dependencies
installed (this repo's local ``venv`` does not - see requirements.txt):

    docker compose exec backend python3 -m unittest \\
        backend.tests.test_language_locale_regression -v

or, to run every test under backend/tests:

    docker compose exec backend python3 -m unittest discover -s backend/tests -v
"""

from __future__ import annotations

import re
import unittest
from typing import Any, Dict, Optional
from unittest.mock import patch

from backend.services.agent.presets.yaml_loader import load_yaml_preset_definitions
from backend.services.agent.specs import AgentSpec, TaskSpec, _resolve_localized_text
from backend.services.agent.tool_selection import _conversation_history_labels
from backend.services.agent.types import AgentCommand
from backend.services.chat.language import DEFAULT_RESPONSE_LANGUAGE
from backend.services.conversation import SECTION_LABELS, _section_labels, build_prompt_with_history

# Matches CJK ideographs and Japanese kana - present in Chinese/Japanese text,
# never in English (aside from occasional short illustrative quotes, e.g. the
# master-agent task description's English variant quoting "用中文回答" as an
# example of what a language-switch request looks like - see
# _cjk_char_ratio()'s threshold check below).
_CJK_RE = re.compile(r"[一-鿿぀-ヿ]")

_SUPPORTED_LANGUAGES = ("English", "Chinese", "Japanese")

# Above this fraction of CJK characters, text reads as CJK-dominant prompt
# content (the actual bug pattern: a whole paragraph hardcoded in Chinese)
# rather than an English paragraph that happens to quote a short non-English
# example phrase or two.
_CJK_DOMINANCE_THRESHOLD = 0.15


def _cjk_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count / len(text)


class ResolveLocalizedTextTest(unittest.TestCase):
    """backend/services/agent/specs/__init__.py::_resolve_localized_text"""

    def setUp(self) -> None:
        self.table = {
            "English": "hello",
            "Chinese": "你好",
            "Japanese": "こんにちは",
        }

    def test_resolves_requested_language(self) -> None:
        self.assertEqual(_resolve_localized_text(self.table, "English"), "hello")
        self.assertEqual(_resolve_localized_text(self.table, "Chinese"), "你好")
        self.assertEqual(_resolve_localized_text(self.table, "Japanese"), "こんにちは")

    def test_falls_back_to_deployment_default_when_language_missing_from_dict(self) -> None:
        partial = {"Chinese": "你好", "Japanese": "こんにちは"}
        # "English" isn't a key in `partial`, and isn't the requested language
        # either (we pass None) - must fall back through DEFAULT_RESPONSE_LANGUAGE.
        result = _resolve_localized_text(partial, None)
        self.assertEqual(result, partial.get(DEFAULT_RESPONSE_LANGUAGE, partial["Chinese"]))

    def test_falls_back_to_first_value_when_no_default_or_english_present(self) -> None:
        only_klingon = {"Klingon": "nuqneH"}
        self.assertEqual(_resolve_localized_text(only_klingon, "French"), "nuqneH")

    def test_plain_string_passes_through_unchanged_regardless_of_language(self) -> None:
        # Backward compatibility: a preset that never migrated to the dict
        # format must keep behaving exactly as before - the string is used
        # verbatim no matter what language is requested.
        for language in (*_SUPPORTED_LANGUAGES, None, "Klingon"):
            self.assertEqual(_resolve_localized_text("plain text", language), "plain text")

    def test_none_and_empty_resolve_to_empty_string(self) -> None:
        self.assertEqual(_resolve_localized_text(None, "English"), "")
        self.assertEqual(_resolve_localized_text("", "English"), "")


class SectionLabelsTest(unittest.TestCase):
    """backend/services/conversation/__init__.py::_section_labels / SECTION_LABELS"""

    def test_all_three_languages_defined_with_matching_keys(self) -> None:
        self.assertEqual(set(SECTION_LABELS.keys()), set(_SUPPORTED_LANGUAGES))
        expected_keys = {"history_summary", "past_conversation", "current_input"}
        for language, table in SECTION_LABELS.items():
            self.assertEqual(set(table.keys()), expected_keys, msg=f"language={language}")

    def test_english_labels_contain_no_cjk_characters(self) -> None:
        # Direct regression guard: the original bug was English sessions
        # getting Chinese-labeled section headers.
        for key, text in SECTION_LABELS["English"].items():
            self.assertNotRegex(text, _CJK_RE, msg=f"English label {key!r} contains CJK: {text!r}")

    def test_resolves_requested_language(self) -> None:
        for language in _SUPPORTED_LANGUAGES:
            self.assertEqual(_section_labels(language), SECTION_LABELS[language])

    def test_unrecognized_or_missing_language_falls_back_to_deployment_default(self) -> None:
        expected = SECTION_LABELS.get(DEFAULT_RESPONSE_LANGUAGE, SECTION_LABELS["English"])
        self.assertEqual(_section_labels(None), expected)
        self.assertEqual(_section_labels("Klingon"), expected)


class BuildPromptWithHistoryTest(unittest.TestCase):
    """backend/services/conversation/__init__.py::build_prompt_with_history

    Uses a conversation_id with no persisted messages so no DB fixtures are
    needed - list_by_conversation() returns [] for an unknown id, which still
    exercises the "[Current Input]"-equivalent label placement (the part of
    the bug this suite cares about) without needing seeded history rows.
    """

    def test_current_input_label_is_localized_english(self) -> None:
        prompt = build_prompt_with_history(
            conversation_id="__nonexistent_regression_test_conversation__",
            new_message="status",
            language="English",
        )
        self.assertIn(SECTION_LABELS["English"]["current_input"], prompt)
        self.assertNotIn(SECTION_LABELS["Chinese"]["current_input"], prompt)

    def test_current_input_label_is_localized_chinese(self) -> None:
        prompt = build_prompt_with_history(
            conversation_id="__nonexistent_regression_test_conversation__",
            new_message="status",
            language="Chinese",
        )
        self.assertIn(SECTION_LABELS["Chinese"]["current_input"], prompt)

    def test_default_language_falls_back_to_deployment_default(self) -> None:
        prompt = build_prompt_with_history(
            conversation_id="__nonexistent_regression_test_conversation__",
            new_message="status",
        )
        expected_labels = SECTION_LABELS.get(DEFAULT_RESPONSE_LANGUAGE, SECTION_LABELS["English"])
        self.assertIn(expected_labels["current_input"], prompt)


class ToolSelectionHistoryLabelsTest(unittest.TestCase):
    """backend/services/agent/tool_selection.py::_conversation_history_labels"""

    def test_includes_every_language_variant(self) -> None:
        labels = _conversation_history_labels()
        for table in SECTION_LABELS.values():
            for label in table.values():
                self.assertIn(label, labels)


def _minimal_agent_record(role: Any, goal: Any = "goal", backstory: Any = "backstory") -> Dict[str, Any]:
    return {
        "id": "test-agent",
        "name": "Test Agent",
        "type": "general",
        "description": "",
        "config": {
            "agents": [{"name": "primary", "role": role, "goal": goal, "backstory": backstory}],
            "tasks": [{"id": "task_main", "description": "do it", "expected_output": "result"}],
        },
    }


class AgentSpecLocalizationTest(unittest.TestCase):
    """AgentSpec.list_from_agent_record() honoring dict-valued role/goal/backstory."""

    def test_dict_valued_role_resolves_per_language(self) -> None:
        record = _minimal_agent_record(
            role={"English": "Dispatcher", "Chinese": "调度员", "Japanese": "ディスパッチャー"}
        )
        for language, expected in (
            ("English", "Dispatcher"),
            ("Chinese", "调度员"),
            ("Japanese", "ディスパッチャー"),
        ):
            specs = AgentSpec.list_from_agent_record(record, language=language)
            self.assertEqual(specs[0].role, expected)

    def test_plain_string_role_is_backward_compatible(self) -> None:
        record = _minimal_agent_record(role="Fixed Role")
        for language in (*_SUPPORTED_LANGUAGES, None):
            specs = AgentSpec.list_from_agent_record(record, language=language)
            self.assertEqual(specs[0].role, "Fixed Role")

    def test_missing_language_param_falls_back_to_deployment_default(self) -> None:
        record = _minimal_agent_record(
            role={"English": "Dispatcher", "Chinese": "调度员", "Japanese": "ディスパッチャー"}
        )
        specs = AgentSpec.list_from_agent_record(record)
        expected = {"English": "Dispatcher", "Chinese": "调度员", "Japanese": "ディスパッチャー"}.get(
            DEFAULT_RESPONSE_LANGUAGE, "Dispatcher"
        )
        self.assertEqual(specs[0].role, expected)


class TaskSpecLocalizationTest(unittest.TestCase):
    """TaskSpec.list_from_agent_record() honoring dict-valued description/expected_output."""

    def test_dict_valued_description_resolves_per_language(self) -> None:
        record = {
            "id": "test-agent",
            "name": "Test Agent",
            "type": "general",
            "config": {
                "tasks": [
                    {
                        "id": "task_main",
                        "description": {"English": "Do the thing: {message}", "Chinese": "做这件事：{message}"},
                        "expected_output": "result",
                    }
                ]
            },
        }
        specs_en = TaskSpec.list_from_agent_record(record, language="English")
        specs_zh = TaskSpec.list_from_agent_record(record, language="Chinese")
        self.assertEqual(specs_en[0].description, "Do the thing: {message}")
        self.assertEqual(specs_zh[0].description, "做这件事：{message}")
        # Placeholders must survive resolution untouched for later templating.
        self.assertIn("{message}", specs_en[0].description)


class PresetYamlLocalizationTest(unittest.TestCase):
    """Structural regression guard over config/agents/presets/*.yaml.

    Loads the real preset files (same loader the running app uses) and
    asserts the fields that get injected into the LLM prompt are either a
    locale-aware dict covering all supported languages, or - if left as a
    plain string - contain no CJK text that would silently dominate an
    English session's prompt. This is the check that would have caught the
    original bug (and would catch a future regression) without needing a
    live LLM call: it fails the moment someone reverts a preset field back to
    a single hardcoded language.
    """

    LOCALE_AWARE_AGENT_FIELDS = ("role", "goal", "backstory")
    LOCALE_AWARE_TASK_FIELDS = ("description", "expected_output")

    @classmethod
    def setUpClass(cls) -> None:
        cls.definitions = {d.id: d for d in load_yaml_preset_definitions()}
        if not cls.definitions:
            raise unittest.SkipTest(
                "No preset YAML definitions found - agents presets directory "
                "unavailable in this environment (see get_agents_presets_dir())."
            )

    def _iter_agent_items(self, definition):
        agents = definition.config.get("agents")
        if isinstance(agents, list) and agents:
            return [a for a in agents if isinstance(a, dict)]
        agent = definition.config.get("agent")
        return [agent] if isinstance(agent, dict) else []

    def _iter_task_items(self, definition):
        tasks = definition.config.get("tasks")
        return [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []

    def _assert_field_locale_safe(self, value: Any, *, where: str) -> None:
        if isinstance(value, dict):
            missing = set(_SUPPORTED_LANGUAGES) - set(value.keys())
            self.assertFalse(
                missing,
                msg=f"{where}: locale dict is missing language(s) {missing} - "
                "every preset that opts into per-language text must cover "
                "English/Chinese/Japanese, or a session in one of the missing "
                "languages silently falls back to a different one.",
            )
            for language in _SUPPORTED_LANGUAGES:
                if language == "English":
                    ratio = _cjk_char_ratio(value[language])
                    self.assertLess(
                        ratio,
                        _CJK_DOMINANCE_THRESHOLD,
                        msg=f"{where}: English variant is {ratio:.0%} CJK characters - reads as "
                        f"CJK-dominant, not English: {value[language]!r}",
                    )
        else:
            # Plain-string (non-localized) field: only a problem if it's the
            # dominant-language prompt content the original bug was about,
            # i.e. it's mostly CJK - a single fixed language wrapped around
            # every session regardless of locale is exactly what broke.
            ratio = _cjk_char_ratio(str(value or ""))
            self.assertLess(
                ratio,
                _CJK_DOMINANCE_THRESHOLD,
                msg=f"{where}: plain-string field is {ratio:.0%} CJK characters and is not locale-aware: "
                f"{value!r}. Either translate it to a language-keyed dict (English/Chinese/Japanese) or "
                "keep it CJK-free so it doesn't dominate non-Chinese sessions.",
            )

    def test_master_agent_preset_is_fully_locale_aware(self) -> None:
        definition = self.definitions.get("preset-master-agent")
        if definition is None:
            self.skipTest("preset-master-agent.yaml not found")
        for agent_item in self._iter_agent_items(definition):
            for field in self.LOCALE_AWARE_AGENT_FIELDS:
                if field in agent_item:
                    self._assert_field_locale_safe(
                        agent_item[field], where=f"preset-master-agent.agents[].{field}"
                    )
        for task_item in self._iter_task_items(definition):
            for field in self.LOCALE_AWARE_TASK_FIELDS:
                if field in task_item:
                    self._assert_field_locale_safe(
                        task_item[field], where=f"preset-master-agent.tasks[].{field}"
                    )

    def test_all_presets_agent_fields_are_locale_safe(self) -> None:
        """Broader sweep: every discovered preset, not just the master one.

        Presets that haven't opted into per-language dicts yet must at least
        not contain hardcoded CJK text in role/goal/backstory, matching the
        constraint that caused this bug for preset-master-agent.
        """
        for preset_id, definition in self.definitions.items():
            for agent_item in self._iter_agent_items(definition):
                for field in self.LOCALE_AWARE_AGENT_FIELDS:
                    if field in agent_item:
                        self._assert_field_locale_safe(
                            agent_item[field], where=f"{preset_id}.agents[].{field}"
                        )

    def test_master_agent_role_resolves_to_english_without_cjk(self) -> None:
        """End-to-end: YAML -> AgentSpec, for the exact language that was broken."""
        definition = self.definitions.get("preset-master-agent")
        if definition is None:
            self.skipTest("preset-master-agent.yaml not found")
        agent_record = {
            "id": definition.id,
            "name": definition.name,
            "type": definition.agent_type,
            "description": definition.description,
            "config": definition.config,
        }
        specs = AgentSpec.list_from_agent_record(agent_record, language="English")
        for spec in specs:
            for field_name, text in (("role", spec.role), ("goal", spec.goal), ("backstory", spec.backstory)):
                self.assertNotRegex(
                    text,
                    _CJK_RE,
                    msg=f"preset-master-agent AgentSpec.{field_name} resolved with language='English' "
                    f"but contains CJK text: {text!r}",
                )


class MasterRuntimeLanguageWiringTest(unittest.TestCase):
    """backend/services/chat/master_runtime.py: command.context["default_language"]
    must reach both AgentSpec.list_from_agent_record() and
    TaskSpec.list_from_agent_record() as the `language` kwarg.

    This is the wiring that connects the session's resolved language to the
    preset-resolution logic tested above; if it regresses (e.g. someone drops
    the kwarg while refactoring _run_crew_blocking), the other tests in this
    file would still pass since they call AgentSpec/TaskSpec directly - only
    this test would catch it.

    _run_crew_blocking() is otherwise heavy (CrewAI kickoff, tool selection,
    event bus wiring), so this test short-circuits it immediately after the
    spec-building calls: AgentSpec.list_from_agent_record() (called first) is
    mocked to return an empty list - harmless, the loop right after it over
    `agent_specs` just does nothing - and TaskSpec.list_from_agent_record()
    (called second) is mocked to raise, stopping execution right there. Both
    calls happen before the raise, so both are asserted on.
    """

    def test_resolved_language_is_passed_to_spec_builders(self) -> None:
        from backend.services.chat import master_runtime

        sentinel = RuntimeError("stop-after-spec-building")
        agent_record = _minimal_agent_record(role="whatever")
        command = AgentCommand(
            user_id="u1",
            agent_id="preset-master-agent",
            message="status",
            context={"default_language": "Japanese", "turn_id": "t1"},
        )

        with patch.object(
            master_runtime.AgentSpec, "list_from_agent_record", return_value=[]
        ) as mock_agent_spec, patch.object(
            master_runtime.TaskSpec, "list_from_agent_record", side_effect=sentinel
        ) as mock_task_spec:
            with self.assertRaises(RuntimeError):
                master_runtime._run_crew_blocking(
                    agent_record=agent_record,
                    command=command,
                    agent_run_id="run1",
                    schedule=lambda coro: None,
                    on_llm_started=lambda: None,
                    on_llm_chunk=lambda chunk: None,
                    on_tool_started=lambda *a, **k: None,
                    on_tool_finished=lambda *a, **k: None,
                    on_tool_failed=lambda *a, **k: None,
                )

        mock_agent_spec.assert_called_once()
        self.assertEqual(mock_agent_spec.call_args.kwargs.get("language"), "Japanese")
        mock_task_spec.assert_called_once()
        self.assertEqual(mock_task_spec.call_args.kwargs.get("language"), "Japanese")


if __name__ == "__main__":
    unittest.main()
