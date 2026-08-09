from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_AGENT_NAME = "primary"


GLOBAL_TOOL_POOL = "global"
DECLARED_TOOL_POOL = "declared"
_AUTO_TOOL_MARKERS = {"auto", "global", "catalog", "all", "*"}


def _parse_tools_value(raw_tools: Any) -> tuple:
    """返回 (tool_names, pool_mode, preferred_names)。

    - ``tools: [...]``（列表 / 单字符串 / 字典）→ declared pool，工具清单即声明列表
    - ``tools: auto`` / ``tools: "global"``  → global pool，候选=全局目录
    - ``tools: {"mode": "auto", "preferred": [...]}`` → global pool，preferred 作为偏好项
    """
    if raw_tools is None:
        return ([], DECLARED_TOOL_POOL, [])

    if isinstance(raw_tools, str):
        normalized = raw_tools.strip().lower()
        if normalized in _AUTO_TOOL_MARKERS:
            return ([], GLOBAL_TOOL_POOL, [])
        if raw_tools.strip():
            return ([raw_tools.strip()], DECLARED_TOOL_POOL, [])
        return ([], DECLARED_TOOL_POOL, [])

    if isinstance(raw_tools, dict):
        mode = str(raw_tools.get("mode") or raw_tools.get("pool") or "").strip().lower()
        preferred = _collect_tool_names(raw_tools.get("preferred") or raw_tools.get("always_include"))
        declared = _collect_tool_names(raw_tools.get("tools") or raw_tools.get("names"))
        if mode in _AUTO_TOOL_MARKERS or (raw_tools.get("auto") is True):
            return (declared, GLOBAL_TOOL_POOL, preferred)
        return (declared, DECLARED_TOOL_POOL, preferred)

    if isinstance(raw_tools, list):
        if len(raw_tools) == 1 and isinstance(raw_tools[0], str) and raw_tools[0].strip().lower() in _AUTO_TOOL_MARKERS:
            return ([], GLOBAL_TOOL_POOL, [])
        return (_collect_tool_names(raw_tools), DECLARED_TOOL_POOL, [])

    return ([], DECLARED_TOOL_POOL, [])


def _collect_tool_names(raw_tools: Any) -> List[str]:
    if not raw_tools:
        return []
    if isinstance(raw_tools, str):
        normalized = raw_tools.strip()
        return [normalized] if normalized else []
    if not isinstance(raw_tools, list):
        return []
    tool_names: List[str] = []
    for item in raw_tools:
        if isinstance(item, str) and item.strip():
            tool_names.append(item.strip())
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("tool") or "").strip()
            if name:
                tool_names.append(name)
    return tool_names


def _normalize_tool_names(raw_tools: Any) -> List[str]:
    """向后兼容：仅抽工具名，不识别 auto 语义。"""
    names, _mode, _preferred = _parse_tools_value(raw_tools)
    return names


def _resolve_localized_text(value: Any, language: Optional[str]) -> str:
    """解析 preset YAML 里的 role/goal/backstory/description/expected_output 字段。

    向后兼容两种写法：
    - 纯字符串：一直按原样使用，与 language 无关（老 preset、简单场景不必迁移）。
    - ``{"English": "...", "Chinese": "...", "Japanese": "..."}`` 字典：按解析出的会话
      语言选取对应文案。这类字段（尤其是 role/goal/backstory）会整段拼进 LLM 的
      system prompt，即使任务描述里显式声明了 default_language，大段固定语言的
      persona 文本仍会把模型的输出语言带偏——所以需要跟 SECTION_LABELS
      （backend/services/conversation/__init__.py）一样按语言选择，而不是任由
      单一语言的大段文本主导整个 prompt。

    Fallback chain when the dict doesn't have an exact `language` key:
    deployment default (DEFAULT_RESPONSE_LANGUAGE) -> "English" -> first
    value in the dict (so a preset that only ships one translation still
    works instead of raising).
    """
    if isinstance(value, dict):
        if language and language in value:
            return str(value[language] or "").strip()
        # Deferred import: same circular-import concern documented in
        # backend/services/conversation/__init__.py's _section_labels().
        from backend.services.chat.language import DEFAULT_RESPONSE_LANGUAGE

        if DEFAULT_RESPONSE_LANGUAGE in value:
            return str(value[DEFAULT_RESPONSE_LANGUAGE] or "").strip()
        if "English" in value:
            return str(value["English"] or "").strip()
        return str(next(iter(value.values()), "") or "").strip()
    return str(value or "").strip()


@dataclass
class AgentSpec:
    """CrewAI Agent 的最小配置表示。"""

    role: str
    goal: str
    backstory: str
    name: str = DEFAULT_AGENT_NAME
    tools: List[str] = field(default_factory=list)
    verbose: bool = False
    memory: bool = False
    allow_delegation: bool = False
    tool_pool: str = DECLARED_TOOL_POOL
    preferred_tool_names: List[str] = field(default_factory=list)

    @classmethod
    def from_agent_record(cls, agent_record: Dict[str, Any], *, language: Optional[str] = None) -> "AgentSpec":
        """向后兼容：返回单 Agent 配置。"""
        specs = cls.list_from_agent_record(agent_record, language=language)
        return specs[0]

    @classmethod
    def list_from_agent_record(
        cls, agent_record: Dict[str, Any], *, language: Optional[str] = None
    ) -> List["AgentSpec"]:
        """支持多 Agent 配置：优先读取 config.agents(list)，回退到 config.agent(dict)。

        ``language`` 用于解析 role/goal/backstory 里按语言分文案的 preset
        （见 ``_resolve_localized_text``）；纯字符串写法的 preset 不受影响。
        未传时按 ``_resolve_localized_text`` 自身的兜底链（部署默认语言 ->
        English -> 字典里第一个值）解析。
        """
        config = dict(agent_record.get("config") or {})
        record_name = str(agent_record.get("name") or "Agent").strip() or "Agent"
        record_description = str(agent_record.get("description") or "").strip()
        record_type = str(agent_record.get("type") or "general").strip() or "general"

        raw_agents = config.get("agents")
        agent_items: List[Dict[str, Any]] = []
        if isinstance(raw_agents, list) and raw_agents:
            for item in raw_agents:
                if isinstance(item, dict):
                    agent_items.append(item)

        if not agent_items:
            singular = config.get("agent") if isinstance(config.get("agent"), dict) else config
            if not isinstance(singular, dict):
                singular = {}
            agent_items = [dict(singular)]

        specs: List[AgentSpec] = []
        used_names: set = set()
        for idx, agent_cfg in enumerate(agent_items):
            raw_name = str(agent_cfg.get("name") or agent_cfg.get("id") or "").strip()
            fallback_name = DEFAULT_AGENT_NAME if idx == 0 else f"agent_{idx + 1}"
            candidate_name = raw_name or fallback_name
            unique_name = candidate_name
            suffix = 2
            while unique_name in used_names:
                unique_name = f"{candidate_name}_{suffix}"
                suffix += 1
            used_names.add(unique_name)

            role = (
                _resolve_localized_text(agent_cfg.get("role"), language)
                or (record_name if idx == 0 else unique_name)
            ).strip() or unique_name
            goal = (
                _resolve_localized_text(agent_cfg.get("goal"), language)
                or record_description
                or f"Use the available tools to complete the assigned {record_type} task."
            ).strip()
            backstory = (
                _resolve_localized_text(agent_cfg.get("backstory"), language)
                or record_description
                or (
                    f"You are {role}, a reliable agent specialized in {record_type} tasks. "
                    "Default to English for the final answer unless the user explicitly requests "
                    "a different language."
                )
            ).strip()

            tool_names, tool_pool, preferred_tool_names = _parse_tools_value(agent_cfg.get("tools"))

            specs.append(
                cls(
                    role=role,
                    goal=goal,
                    backstory=backstory,
                    name=unique_name,
                    tools=tool_names,
                    verbose=bool(agent_cfg.get("verbose", False)),
                    memory=bool(agent_cfg.get("memory", False)),
                    allow_delegation=bool(agent_cfg.get("allow_delegation", False)),
                    tool_pool=tool_pool,
                    preferred_tool_names=preferred_tool_names,
                )
            )

        if not specs:
            specs.append(
                cls(
                    role=record_name,
                    goal=f"Use the available tools to complete the assigned {record_type} task.",
                    backstory=(
                        f"You are {record_name}, a reliable agent specialized in {record_type} tasks. "
                        "Default to English for the final answer unless the user explicitly requests "
                        "a different language."
                    ),
                    name=DEFAULT_AGENT_NAME,
                )
            )
        return specs


@dataclass
class TaskSpec:
    """CrewAI Task 的最小配置表示。"""

    task_id: str
    description: str
    expected_output: str
    context: List[str] = field(default_factory=list)
    agent_name: Optional[str] = None

    @classmethod
    def list_from_agent_record(
        cls, agent_record: Dict[str, Any], *, language: Optional[str] = None
    ) -> List["TaskSpec"]:
        """``language`` resolves per-language ``description``/``expected_output``
        dicts the same way AgentSpec resolves role/goal/backstory - see
        ``_resolve_localized_text``. Resolved text may still contain
        ``{message}``/``{default_language}``/etc. placeholders; those are
        filled in later by the caller's own templating, unaffected by this.
        """
        config = dict(agent_record.get("config") or {})
        raw_tasks = config.get("tasks")
        if isinstance(raw_tasks, list) and raw_tasks:
            task_specs: List[TaskSpec] = []
            for idx, item in enumerate(raw_tasks, start=1):
                if not isinstance(item, dict):
                    continue
                task_id = str(item.get("id") or f"task_{idx}").strip() or f"task_{idx}"
                description = (
                    _resolve_localized_text(item.get("description"), language)
                    or "Complete the user's request using the available context and tools. Input: {message}"
                ).strip()
                expected_output = (
                    _resolve_localized_text(item.get("expected_output"), language)
                    or "A complete, accurate, and concise result in markdown format."
                ).strip()
                context = [str(v).strip() for v in (item.get("context") or []) if str(v).strip()]
                agent_name = str(
                    item.get("agent_name")
                    or item.get("agent")
                    or item.get("agent_id")
                    or ""
                ).strip() or None
                task_specs.append(
                    cls(
                        task_id=task_id,
                        description=description,
                        expected_output=expected_output,
                        context=context,
                        agent_name=agent_name,
                    )
                )
            if task_specs:
                return task_specs

        return [
            cls(
                task_id="task_main",
                description="Complete the user's request. Input: {message}",
                expected_output="A complete, accurate, and concise result in markdown format.",
                context=[],
                agent_name=None,
            )
        ]
