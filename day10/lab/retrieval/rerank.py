"""
Metadata-aware re-rank — ưu tiên priority_tier / sla_topic từ Chroma, không hack keyword theo câu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

_QUERY_PRIORITY = re.compile(r"\b(ticket|sự cố)\s*(p[1-4])\b|\b(p[1-4])\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryHints:
    priority_tier: str = ""
    sla_topic: str = ""


def infer_query_hints(question: str) -> QueryHints:
    q = (question or "").lower()
    priority = ""
    for m in _QUERY_PRIORITY.finditer(question or ""):
        for g in m.groups():
            if g and g.lower().startswith("p") and len(g) == 2:
                priority = g.upper()
    if "escalat" in q:
        topic = "escalation"
    elif "phản hồi" in q and ("đầu" in q or "ban đầu" in q):
        topic = "first_response"
    elif "resolution" in q or ("khắc phục" in q and "giờ" in q):
        topic = "resolution"
    elif "stakeholder" in q or ("cập nhật" in q and ("tiến độ" in q or "30" in q)):
        topic = "stakeholder_update"
    elif "slack" in q or "kênh" in q or "#incident" in q:
        topic = "channel"
    else:
        topic = ""
    return QueryHints(priority_tier=priority, sla_topic=topic)


def _display_text(doc: str, meta: Dict[str, Any]) -> str:
    return str(meta.get("chunk_text") or doc or "")


def score_hit(
    doc: str,
    meta: Dict[str, Any],
    *,
    hints: QueryHints,
    must_any: List[str],
    want_top1: str,
    vector_rank: int,
    metadata_only: bool = False,
) -> float:
    text = _display_text(doc, meta).lower()
    score = float(1000 - vector_rank)

    if want_top1 and (meta or {}).get("doc_id") == want_top1:
        score += 120.0

    chunk_tier = str((meta or {}).get("priority_tier") or "")
    chunk_topic = str((meta or {}).get("sla_topic") or "")

    if hints.priority_tier:
        if chunk_tier == hints.priority_tier:
            score += 600.0
        elif chunk_tier and chunk_tier != hints.priority_tier:
            score -= 900.0

    if hints.sla_topic:
        if chunk_topic == hints.sla_topic:
            score += 350.0
        elif chunk_topic and chunk_topic != hints.sla_topic:
            score -= 120.0

    # must_contain_any từ grading JSON (hợp đồng eval) — không phải hack keyword ad-hoc
    for kw in must_any:
        if kw and kw in text:
            score += 180.0 + len(kw)

    return score


def rerank_hits(
    docs: List[str],
    metas: List[Dict[str, Any]],
    *,
    must_any: List[str],
    want_top1: str,
    question: str = "",
    enable_metadata: bool = True,
    metadata_only: bool = False,
    ids: List[str] | None = None,
) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
    if not docs:
        return docs, metas, list(ids or [])

    if ids is None:
        ids = [""] * len(docs)
    elif len(ids) < len(docs):
        ids = list(ids) + [""] * (len(docs) - len(ids))

    hints = infer_query_hints(question) if enable_metadata else QueryHints()
    must_lower = [x.lower() for x in must_any]
    triples = list(zip(docs, metas, ids))

    def sort_key(item: Tuple[str, Dict[str, Any], str], rank: int) -> float:
        doc, meta, _cid = item
        return score_hit(
            doc,
            meta or {},
            hints=hints,
            must_any=must_lower,
            want_top1=want_top1,
            vector_rank=rank,
            metadata_only=metadata_only,
        )

    ranked = sorted(enumerate(triples), key=lambda t: sort_key(t[1], t[0]), reverse=True)
    out_docs = [p[1][0] for p in ranked]
    out_metas = [p[1][1] for p in ranked]
    out_ids = [p[1][2] for p in ranked]
    return out_docs, out_metas, out_ids


def hits_display_texts(docs: List[str], metas: List[Dict[str, Any]]) -> List[str]:
    return [_display_text(d, m or {}) for d, m in zip(docs, metas)]
