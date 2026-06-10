"""Tests — retrieval metadata + re-rank."""

from __future__ import annotations

from retrieval.chunk_metadata import (
    build_embed_document,
    chunk_retrieval_metadata,
    infer_priority_tier,
)
from retrieval.rerank import infer_query_hints, rerank_hits


def test_infer_priority_from_ticket_section_bullet():
    text = "Ticket P1: Escalation: Tự động escalate lên Senior Engineer nếu không có phản hồi trong 10 phút."
    assert infer_priority_tier("sla_p1_2026", text) == "P1"


def test_chunk_metadata_escalation_topic():
    text = "Ticket P1: Escalation: Tự động escalate sau 10 phút không phản hồi."
    meta = chunk_retrieval_metadata("sla_p1_2026", text)
    assert meta["priority_tier"] == "P1"
    assert meta["sla_topic"] == "escalation"


def test_embed_document_has_structured_prefix():
    meta = {"priority_tier": "P1", "sla_topic": "escalation"}
    doc = build_embed_document("Escalation 10 phút.", meta)
    assert doc.startswith("[P1|escalation]")


def test_metadata_rerank_p1_escalation_beats_p2():
    docs = [
        "[P2|escalation] Ticket P2: Escalation sau 90 phút.",
        "[P1|escalation] Ticket P1: Escalation sau 10 phút.",
    ]
    metas = [
        {
            "doc_id": "sla_p1_2026",
            "chunk_text": "Ticket P2: Escalation sau 90 phút.",
            "priority_tier": "P2",
            "sla_topic": "escalation",
        },
        {
            "doc_id": "sla_p1_2026",
            "chunk_text": "Ticket P1: Escalation sau 10 phút.",
            "priority_tier": "P1",
            "sla_topic": "escalation",
        },
    ]
    question = "Nếu không có phản hồi với ticket P1 sau bao lâu thì hệ thống auto escalate?"
    hints = infer_query_hints(question)
    assert hints.priority_tier == "P1"
    assert hints.sla_topic == "escalation"

    _docs, ranked_metas, _ids = rerank_hits(
        docs,
        metas,
        must_any=["10 phút"],
        want_top1="sla_p1_2026",
        question=question,
        ids=["p2", "p1"],
    )
    assert ranked_metas[0]["priority_tier"] == "P1"
    assert "10 phút" in ranked_metas[0]["chunk_text"]


def test_vector_order_wrong_metadata_rerank_fixes():
    """Mô phỏng embedding xếp P2 trước P1 — metadata re-rank đảo lại."""
    docs = ["p2 doc", "p1 doc"]
    metas = [
        {"doc_id": "sla_p1_2026", "chunk_text": "Ticket P2: 90 phút", "priority_tier": "P2"},
        {
            "doc_id": "sla_p1_2026",
            "chunk_text": "Ticket P1: 10 phút",
            "priority_tier": "P1",
            "sla_topic": "escalation",
        },
    ]
    _docs, ranked_metas, _ids = rerank_hits(
        docs,
        metas,
        must_any=["10 phút"],
        want_top1="sla_p1_2026",
        question="ticket P1 auto escalate?",
        ids=["c2", "c1"],
    )
    assert ranked_metas[0]["priority_tier"] == "P1"
