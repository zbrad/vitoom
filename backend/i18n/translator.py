"""Translation helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .locale import detect_cli_locale
from .messages.en_US import MESSAGES as EN_MESSAGES
from .messages.ja_JP import MESSAGES as JA_MESSAGES
from .messages.zh_CN import MESSAGES as ZH_MESSAGES

_CATALOGS: Dict[str, Dict[str, str]] = {
    "zh-CN": ZH_MESSAGES,
    "en-US": EN_MESSAGES,
    "ja-JP": JA_MESSAGES,
}

# Deployment-level fallback locale, resolved once at import time from the
# same VITOOM_LOCALE/LC_ALL/LANG signal used elsewhere in this series (see
# chat/language.py's DEFAULT_RESPONSE_LANGUAGE). Was hardcoded to
# backend.i18n.locale.DEFAULT_LOCALE ("zh-CN"); that constant still governs
# live per-request locale resolution (get_locale_from_request()) and is
# untouched - this only changes which catalog a missing translation key
# falls back to.
FALLBACK_LOCALE = detect_cli_locale()


def get_messages(locale: str) -> Dict[str, str]:
    return _CATALOGS.get(locale, _CATALOGS[FALLBACK_LOCALE])


def t(key: str, locale: str, **params: Any) -> str:
    messages = get_messages(locale)
    template = messages.get(key)
    if not template:
        # A key missing from the requested locale's catalog: try the
        # deployment default next, then English, before giving up and
        # showing the raw key. Two lookups in the worst case, but a missing
        # translation should degrade to *some* readable language, not a
        # dotted key leaking into an API response or chat message.
        template = get_messages(FALLBACK_LOCALE).get(key) or EN_MESSAGES.get(key, key)
    if not params:
        return template
    try:
        return template.format(**params)
    except Exception:
        return template


def build_message_params(details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not details:
        return {}
    params: Dict[str, Any] = {}
    for key in ("user_id", "email", "model", "model_key", "task_id", "parameter", "seconds", "max_size", "progress"):
        if key in details and details[key] is not None:
            params[key] = details[key]
    if "model_key" in params and "model" not in params:
        params["model"] = params["model_key"]
    return params
