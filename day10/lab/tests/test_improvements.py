"""Tests — Phase 1 & 3 improvements."""

from __future__ import annotations

from quality.cleaned_schema import validate_cleaned_rows
from transform.cleaning_rules import (
    _collapse_repeated_tokens,
    clean_rows,
    quarantine_reason_counts,
)


def test_collapse_repeated_tokens_two_times():
    text = "7 ngày làm việc làm việc kể từ xác nhận"
    assert "làm việc làm việc" not in _collapse_repeated_tokens(text)


def test_collapse_repeated_tokens_three_times():
    text = "làm việc làm việc làm việc"
    assert _collapse_repeated_tokens(text) == "làm việc"


def test_sort_before_dedupe_keeps_newer_hr():
    rows = [
        {
            "doc_id": "hr_leave_policy",
            "chunk_text": "Nhân viên dưới 3 năm kinh nghiệm được 12 ngày phép năm theo chính sách 2026.",
            "effective_date": "2026-01-01",
            "exported_at": "2026-04-11T00:00:00",
        },
        {
            "doc_id": "hr_leave_policy",
            "chunk_text": "Nhân viên dưới 3 năm kinh nghiệm được 12 ngày phép năm theo chính sách 2026.",
            "effective_date": "2026-03-01",
            "exported_at": "2026-04-01T00:00:00",
        },
    ]
    cleaned, quarantine = clean_rows(rows)
    hr_rows = [
        r
        for r in cleaned
        if r["doc_id"] == "hr_leave_policy"
        and "12 ngày phép năm" in r["chunk_text"]
    ]
    assert len(hr_rows) == 1
    assert hr_rows[0]["effective_date"] == "2026-03-01"
    assert sum(1 for q in quarantine if q.get("reason") == "duplicate_chunk_text") >= 1


def test_canonical_sla_chunks_merged():
    rows = [
        {
            "doc_id": "sla_p1_2026",
            "chunk_text": "Ticket P1 có SLA phản hồi ban đầu 15 phút và resolution trong 4 giờ.",
            "effective_date": "2025-07-15",
            "exported_at": "2026-04-04T00:00:00",
        },
    ]
    cleaned, _ = clean_rows(rows)
    texts = " ".join(r["chunk_text"] for r in cleaned if r["doc_id"] == "sla_p1_2026")
    assert "10 phút" in texts
    assert "30 phút" in texts


def test_quarantine_reason_counts():
    quarantine = [
        {"reason": "unknown_doc_id"},
        {"reason": "unknown_doc_id"},
        {"reason": "duplicate_chunk_text"},
    ]
    counts = quarantine_reason_counts(quarantine)
    assert counts["unknown_doc_id"] == 2
    assert counts["duplicate_chunk_text"] == 1


def test_pydantic_validate_clean_row():
    row = {
        "chunk_id": "x_1_abc",
        "doc_id": "policy_refund_v4",
        "chunk_text": "Yêu cầu hoàn tiền trong 7 ngày làm việc.",
        "effective_date": "2026-01-01",
        "exported_at": "2026-04-01T00:00:00",
    }
    valid, errors = validate_cleaned_rows([row])
    assert len(valid) == 1
    assert errors == []


def test_strip_corruption_markers():
    from transform.cleaning_rules import _strip_corruption_markers

    assert _strip_corruption_markers("!!!Ticket P1 có SLA") == "Ticket P1 có SLA"


def test_pydantic_rejects_short_chunk():
    row = {
        "chunk_id": "x_1_abc",
        "doc_id": "policy_refund_v4",
        "chunk_text": "short",
        "effective_date": "2026-01-01",
        "exported_at": "2026-04-01T00:00:00",
    }
    _, errors = validate_cleaned_rows([row])
    assert len(errors) >= 1


def test_resolve_stale_snapshot_aligns_to_reference():
    from datetime import datetime, timezone

    from monitoring.freshness_check import resolve_data_snapshot_timestamp

    now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    ref = "2026-06-10T12:00:00+00:00"
    effective, meta = resolve_data_snapshot_timestamp(
        "2026-04-11T00:00:00",
        reference_ts=ref,
        sla_hours=720,
        now=now,
        align_stale=True,
    )
    assert meta["aligned"] is True
    assert meta["reason"] == "source_snapshot_stale_aligned_to_reference"
    assert effective == ref


def test_resolve_fresh_snapshot_not_aligned():
    from datetime import datetime, timezone

    from monitoring.freshness_check import resolve_data_snapshot_timestamp

    now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    source = "2026-06-09T00:00:00"
    effective, meta = resolve_data_snapshot_timestamp(
        source,
        reference_ts="2026-06-10T12:00:00+00:00",
        sla_hours=720,
        now=now,
        align_stale=True,
    )
    assert meta["aligned"] is False
    assert effective == source


def test_refund_fix_regex_variants():
    from transform.cleaning_rules import _apply_refund_window_fix_text

    assert "7 ngày làm việc" in _apply_refund_window_fix_text("Hoàn trong 14 ngày")
    assert "7 ngày làm việc" in _apply_refund_window_fix_text("14 ngày làm việc kể từ")


def test_access_control_level4_canonical():
    cleaned, _ = clean_rows([])
    ac = [r for r in cleaned if r["doc_id"] == "access_control_sop"]
    blob = " ".join(r["chunk_text"] for r in ac)
    assert "Level 4" in blob and "CISO" in blob


def test_whitespace_chunk_quarantined():
    rows = [
        {
            "doc_id": "it_helpdesk_faq",
            "chunk_text": "   ",
            "effective_date": "2026-01-01",
            "exported_at": "2026-04-01T00:00:00",
        },
    ]
    cleaned, q = clean_rows(rows)
    assert sum(1 for x in q if x.get("reason") == "missing_chunk_text") == 1
    assert all((r.get("chunk_text") or "").strip() for r in cleaned)


def test_invalid_doc_quarantined():
    rows = [
        {
            "doc_id": "invalid_doc_xzyxyx",
            "chunk_text": "Ticket P1 có SLA phản hồi ban đầu 15 phút.",
            "effective_date": "2025-03-01",
            "exported_at": "2026-04-03T00:00:00",
        },
    ]
    _, q = clean_rows(rows)
    assert q[0]["reason"] == "unknown_doc_id"


def test_build_canonical_cleaned_rows_from_docs():
    from transform.cleaning_rules import build_canonical_cleaned_rows

    rows = build_canonical_cleaned_rows(exported_at="2026-06-10T00:00:00+00:00")
    assert len(rows) >= 70
    by_doc = {}
    for r in rows:
        by_doc[r["doc_id"]] = by_doc.get(r["doc_id"], 0) + 1
    assert by_doc.get("it_helpdesk_faq", 0) >= 15
    assert all(r.get("chunk_id") and r.get("effective_date") for r in rows)


def test_collapse_long_repeated_clause():
    from transform.cleaning_rules import _collapse_repeated_tokens

    text = "Yêu cầu được gửi trong vòng 7 ngày làm việc kể từ thời điểm xác nhận đơn hàng. " * 3
    out = _collapse_repeated_tokens(text)
    assert out.count("Yêu cầu được gửi") == 1
