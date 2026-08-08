"""Resolve the default response language for a chat session.

Priority handled by callers, not this module:
    1. explicit in-conversation language request (the LLM detects this itself
       from the full conversation history it's given — see no_tool_runner.py
       and the preset task descriptions)
    2. this session's browser-reported locale, if one was ever received
       (see backend/websocket/chat_routes.py, backend/api/chat/routes.py)
    3. DEFAULT_RESPONSE_LANGUAGE (final fallback)

This module only implements step 2/3: locale -> human-readable language name.
"""

from __future__ import annotations

from typing import Optional

from backend.i18n.locale import detect_cli_locale

LOCALE_LANGUAGE_NAMES = {
    "zh-CN": "Chinese",
    "en-US": "English",
    "ja-JP": "Japanese",
}

# Deployment-level fallback, resolved once at import time (not per-request):
# detect_cli_locale() reads VITOOM_LOCALE, then LC_ALL/LANG, defaulting to
# "en-US" if none resolve to a supported locale. VITOOM_LOCALE is the same
# variable scripts/setup_vitoom.py captures from the build host's OS locale
# into .env during image build prep, and docker-compose.yml passes it through
# to the running backend container - so a China-built deployment defaults to
# Chinese and an unconfigured/English-locale build defaults to English,
# without needing a per-session browser locale.
DEFAULT_RESPONSE_LANGUAGE = LOCALE_LANGUAGE_NAMES[detect_cli_locale()]


def resolve_default_language(locale: Optional[str]) -> str:
    """Map a normalized locale (e.g. "zh-CN") to a language name for prompts.

    Falls back to DEFAULT_RESPONSE_LANGUAGE when `locale` is missing or not
    one of the frontend's supported locales.
    """
    return LOCALE_LANGUAGE_NAMES.get(locale or "", DEFAULT_RESPONSE_LANGUAGE)
