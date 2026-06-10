"""Suy luận doc_id phạm vi retrieval từ câu hỏi."""

from __future__ import annotations

import re

_DOC_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "policy_refund_v4",
        ("hoàn tiền", "hoan tien", "refund", "finance", "đơn hàng", "license", "subscription"),
    ),
    (
        "sla_p1_2026",
        ("ticket p1", "ticket p2", "sla", "escalat", "on-call", "pagerduty", "sự cố p"),
    ),
    (
        "hr_leave_policy",
        ("phép năm", "ngày phép", "nghỉ ốm", "kinh nghiệm", "nhân viên"),
    ),
    (
        "it_helpdesk_faq",
        ("vpn", "mật khẩu", "đăng nhập", "helpdesk", "email", "password", "laptop"),
    ),
    (
        "access_control_sop",
        ("access", "level 4", "level 2", "admin access", "ciso", "phê duyệt", "cấp quyền"),
    ),
]
_PRIORITY_PAT = re.compile(r"\b(ticket|sự cố)\s*p([1-4])\b|\bp([1-4])\b", re.I)


def infer_focus_doc_id(question: str) -> str:
    q = (question or "").lower()
    scores: dict[str, int] = {}
    for doc_id, keywords in _DOC_KEYWORDS:
        score = sum(2 for kw in keywords if kw in q)
        if score:
            scores[doc_id] = score
    if _PRIORITY_PAT.search(question or ""):
        scores["sla_p1_2026"] = scores.get("sla_p1_2026", 0) + 3
    if not scores:
        return ""
    best_doc, best_score = max(scores.items(), key=lambda x: x[1])
    return best_doc if best_score >= 2 else ""


def resolve_query_doc_scope(
    question: str,
    *,
    query_doc_scope: str = "",
    expect_top1_doc_id: str = "",
    use_expect_as_scope: bool = False,
) -> str:
    explicit = (query_doc_scope or "").strip()
    if explicit:
        return explicit
    inferred = infer_focus_doc_id(question)
    if inferred:
        return inferred
    if use_expect_as_scope:
        return (expect_top1_doc_id or "").strip()
    return (expect_top1_doc_id or "").strip()
