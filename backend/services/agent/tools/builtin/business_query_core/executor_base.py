"""Shared executor primitives for business query tools."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.services.agent.tools.builtin._fallback_strings import business_query_string


def placeholder_permission_check(query_spec: Dict[str, Any], *, domain: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    return {
        "enabled": False,
        "status": "placeholder_passed",
        "note": business_query_string("permission_check_note", language),
        "domain": domain or query_spec.get("domain"),
        "query_spec_intent": query_spec.get("intent"),
    }


def placeholder_cost_check(query_spec: Dict[str, Any], *, language: Optional[str] = None) -> Dict[str, Any]:
    return {
        "enabled": False,
        "status": "placeholder_passed",
        "note": business_query_string("cost_check_note", language),
        "limit": query_spec.get("limit"),
    }
