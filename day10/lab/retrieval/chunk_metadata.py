"""
Gắn metadata retrieval có cấu trúc lúc index — không phụ thuộc cấu hình từng câu hỏi.
"""

from __future__ import annotations

import re
from typing import Any, Dict

_PRIORITY_IN_TEXT = re.compile(
    r"\b(ticket|sự cố|incident)\s*(p[1-4])\b|"
    r"\b(p[1-4])\s*[—\-]\s*(critical|high|medium|low)\b|"
    r"\bescalation\s*(p[1-4])\b|"
    r"#incident-(p[1-4])\b",
    re.IGNORECASE,
)


def infer_priority_tier(doc_id: str, text: str) -> str:
    if doc_id != "sla_p1_2026":
        return ""
    blob = (text or "").lower()
    for m in _PRIORITY_IN_TEXT.finditer(text or ""):
        for g in m.groups():
            if g and g.lower().startswith("p") and len(g) == 2:
                return g.upper()
    if "incident-p1" in blob or "escalation p1" in blob or "stakeholder p1" in blob:
        return "P1"
    if "incident-p2" in blob or "escalation p2" in blob:
        return "P2"
    return ""


def infer_sla_topic(text: str) -> str:
    blob = (text or "").lower()
    if "escalat" in blob:
        return "escalation"
    if "phản hồi ban đầu" in blob or "first response" in blob or "phản hồi đầu" in blob:
        return "first_response"
    if "resolution" in blob or "khắc phục" in blob or "xử lý và khắc phục" in blob:
        return "resolution"
    if "stakeholder" in blob or ("30 phút" in blob and ("update" in blob or "cập nhật" in blob)):
        return "stakeholder_update"
    if "#incident" in blob or "slack" in blob or "hotline" in blob:
        return "channel"
    if "critical" in blob or "định nghĩa" in blob or "workaround" in blob:
        return "definition"
    return "general"


def chunk_retrieval_metadata(doc_id: str, chunk_text: str) -> Dict[str, str]:
    priority = infer_priority_tier(doc_id, chunk_text)
    topic = infer_sla_topic(chunk_text) if doc_id == "sla_p1_2026" else ""
    meta: Dict[str, str] = {}
    if priority:
        meta["priority_tier"] = priority
    if topic:
        meta["sla_topic"] = topic
    return meta


def build_embed_document(chunk_text: str, retrieval_meta: Dict[str, Any]) -> str:
    """
    Prefix có cấu trúc cho vector index — giúp embedding thuần phân biệt P1/P2 và topic.
  Text gốc vẫn nằm trong metadata['chunk_text'] để hiển thị / keyword check.
    """
    labels: list[str] = []
    tier = str(retrieval_meta.get("priority_tier") or "")
    topic = str(retrieval_meta.get("sla_topic") or "")
    if tier:
        labels.append(tier)
    if topic:
        labels.append(topic)
    if not labels:
        return chunk_text
    return f"[{'|'.join(labels)}] {chunk_text}"
