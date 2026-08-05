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

LOCALE_LANGUAGE_NAMES = {
    "zh-CN": "Chinese",
    "en-US": "English",
    "ja-JP": "Japanese",
}

DEFAULT_RESPONSE_LANGUAGE = "English"


def resolve_default_language(locale: Optional[str]) -> str:
    """Map a normalized locale (e.g. "zh-CN") to a language name for prompts.

    Falls back to DEFAULT_RESPONSE_LANGUAGE when `locale` is missing or not
    one of the frontend's supported locales.
    """
    return LOCALE_LANGUAGE_NAMES.get(locale or "", DEFAULT_RESPONSE_LANGUAGE)
