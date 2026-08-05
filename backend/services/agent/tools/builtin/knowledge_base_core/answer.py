from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from backend.services.agent.tools.builtin.business_query_core.planner_base import run_agent_planner_completion
from backend.services.agent.tools.builtin._fallback_strings import kb_headers, kb_string

from .models import RetrievalHit


def _source_label(hit: RetrievalHit) -> str:
    parts = [f"《{hit.file_name}》"]
    section = str(hit.source.get("section_path") or "").strip()
    if section:
        parts.append(section)
    page = hit.source.get("page_start") or hit.source.get("page_end")
    if page:
        parts.append(f"页码 {page}")
    return " / ".join(parts)


def _snippet(text: str, *, limit: int = 220) -> str:
    normalized = " ".join(str(text or "").split())
    return normalized[:limit] + ("..." if len(normalized) > limit else "")


def build_context(hits: Iterable[RetrievalHit], *, max_chars: int) -> str:
    blocks: List[str] = []
    used = 0
    for index, hit in enumerate(hits, start=1):
        text = hit.text or str(hit.source.get("metadata_text") or "")
        block = (
            f"[{index}] 来源：{_source_label(hit)}\n"
            f"文件路径：{hit.source.get('canonical_path') or hit.source.get('source_uri') or ''}\n"
            f"内容：{text.strip()}"
        ).strip()
        if not block:
            continue
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def format_sources(hits: Iterable[RetrievalHit]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for hit in hits:
        sources.append(
            {
                "chunk_id": hit.chunk_id,
                "document_id": hit.document_id,
                "file_name": hit.file_name,
                "section_path": hit.source.get("section_path") or "",
                "page_start": hit.source.get("page_start"),
                "page_end": hit.source.get("page_end"),
                "canonical_path": hit.source.get("canonical_path") or "",
                "source_uri": hit.source.get("source_uri") or "",
                "score": hit.score,
            }
        )
    return sources


def evidence_only_answer(query: str, hits: List[RetrievalHit], *, language: Optional[str] = None) -> str:
    headers = kb_headers(language)
    if not hits:
        return (
            f"{headers['answer']}\n\n{kb_string('no_evidence', language)}\n\n"
            f"{headers['evidence']}\n\n- {kb_string('none', language)}\n\n"
            f"{headers['not_covered']}\n\n- {kb_string('no_evidence', language)}"
        )
    display_hits = _lexically_matching_hits(query, hits)
    if not display_hits:
        display_hits = hits[:3]
    lines = [headers["answer"], "", kb_string("found_related", language), "", headers["evidence"]]
    for hit in display_hits:
        lines.append(f"- {_source_label(hit)}：{_snippet(hit.text or hit.source.get('metadata_text') or '')}")
    lines.extend(["", headers["not_covered"], "", f"- {kb_string('no_body_text', language).format(query=query)}"])
    return "\n".join(lines)


def _is_existence_query(query: str) -> bool:
    return bool(re.search(r"(有吗|有没有|是否有|找一下|查一下|资料|文件|文档)", str(query or "")))


def _query_keywords(query: str) -> List[str]:
    text = str(query or "").strip()
    text = re.sub(r"(有没有|是否有|有吗|找一下|查一下|资料|文件|文档|知识库|里面|里|关于|的)", " ", text)
    keywords = [item.strip().lower() for item in re.split(r"[\s,，。！？；;:：/\\()\[\]{}<>《》\"']+", text) if len(item.strip()) >= 2]
    return keywords


def _lexically_matching_hits(query: str, hits: List[RetrievalHit]) -> List[RetrievalHit]:
    keywords = _query_keywords(query)
    if not keywords:
        return hits
    matched: List[RetrievalHit] = []
    for hit in hits:
        haystack = " ".join(
            str(value or "")
            for value in (
                hit.file_name,
                hit.title,
                hit.source.get("metadata_text"),
                hit.text,
            )
        ).lower()
        if any(keyword in haystack for keyword in keywords):
            matched.append(hit)
    return matched


def generate_answer(
    query: str,
    hits: List[RetrievalHit],
    *,
    user_id: str,
    max_context_chars: int,
    language: Optional[str] = None,
) -> str:
    if not hits:
        return evidence_only_answer(query, hits, language=language)
    if _is_existence_query(query):
        return evidence_only_answer(query, hits, language=language)
    context = build_context(hits, max_chars=max_context_chars)
    headers = kb_headers(language)
    messages = [
        {
            "role": "system",
            "content": (
                "你是本地知识库问答助手。只能基于给定检索片段回答；证据不足时必须明确说明未找到足够依据。"
                "不得编造不存在的文档、页码或结论。输出固定包含以下三个小节标题（原样使用，不要翻译成其他写法）："
                f"{headers['answer']}、{headers['evidence']}、{headers['not_covered']}。"
            ),
        },
        {
            "role": "user",
            "content": f"用户问题：{query}\n\n检索片段：\n{context}",
        },
    ]
    try:
        return run_agent_planner_completion(
            messages, user_id=user_id, error_label="knowledge base answer", language=language
        )
    except Exception:
        return evidence_only_answer(query, hits, language=language)


def append_debug(markdown: str, *, sources: List[Dict[str, Any]], debug: Dict[str, Any]) -> str:
    payload = json.dumps({"sources": sources, "debug": debug}, ensure_ascii=False, indent=2)
    return f"{markdown.rstrip()}\n\n### Debug\n\n```json\n{payload}\n```"
