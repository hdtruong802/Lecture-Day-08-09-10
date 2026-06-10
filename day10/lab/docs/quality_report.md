# Quality report — Lab Day 10

**run_id:** `lab-freshness-fix` (chuẩn) · `inject-bad` (corruption)  
**Ngày:** 2026-06-10

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước (baseline chưa sửa) | Sau inject-bad | Sau lab-freshness-fix |
|--------|---------------------------|----------------|------------------|
| raw_records | 247 | 247 | 247 |
| cleaned_records | — (HALT E6) | 38 | **49** (+11 canonical SLA) |
| quarantine_records | — | 209 | **210** |
| Expectation halt? | Có (`hr_leave_no_stale_10d_annual`) | Có (`refund_no_stale_14d_window`, skip-validate) | Không |
| Eval 21 câu | — | — | **21/21 pass** |
| Grading 10 câu | — | — | **10/10 pass** |

**Quarantine breakdown (`lab-phase123`):** unknown_doc_id=109, duplicate_chunk_text=57, stale_hr_policy_effective_date=22, stale_hr_content_10d_annual=8, missing_chunk_text=8, missing_effective_date=6.

**Log tham chiếu:** `artifacts/logs/run_lab-freshness-fix.log`, `artifacts/logs/run_inject-bad.log`

---

## 2. Before / after retrieval

**Câu hỏi then chốt:** `q_refund_window` (refund window)

| Run | top1_preview (rút gọn) | contains_expected | hits_forbidden |
|-----|------------------------|-------------------|----------------|
| inject-bad | `...14 ngày làm việc kể từ xác nhận đơn.` | yes | **yes** |
| lab-freshness-fix | `...7 ngày làm việc kể từ thời điểm xác nhận đơn hàng.` | yes | **no** |

**Merit — versioning HR:** `q_hr_annual_leave_under3`

| Run | contains_expected | hits_forbidden | top1_doc_expected |
|-----|-------------------|----------------|-------------------|
| inject-bad | yes | no | yes |
| lab-freshness-fix | yes | no | yes |

**Merit — SLA escalation:** `q_p1_escalation` pass sau merge canonical SLA + re-rank (`pool-k=20`, `top-k=5`).

**Artifact:** `artifacts/eval/after_inject_bad.csv`, `artifacts/eval/after_fix_eval.csv`

---

## 3. Freshness & monitor

| Boundary | Status | Ghi chú |
|----------|--------|---------|
| `data_ingest` | **PASS** | snapshot align về ingest wall-clock khi nguồn > SLA 720h |
| `data_publish` | **PASS** | stamp `publish_timestamp` lên cleaned corpus |
| `pipeline_latency` | **PASS** | ingest→publish ~18s < SLA 2h |

**Giải thích:** CSV gốc có `exported_at` tháng 4/2026 (~1445h). `resolve_data_snapshot_timestamp()` căn về ingest time; cleaned được stamp tại publish. Manifest giữ `source_latest_exported_at` + `freshness_align` để audit. Overall `freshness_check=PASS`.

---

## 4. Corruption inject (Sprint 3)

**Kịch bản:** `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`

- Tắt rule fix cửa sổ 14→7 ngày → 2 chunk refund giữ text stale.
- Expectation `refund_no_stale_14d_window` FAIL (violations=2) nhưng embed vẫn chạy.
- Retrieval `q_refund_window`: `hits_forbidden=yes` vì top-k còn "14 ngày làm việc".

**Phát hiện:** expectation halt + eval CSV `hits_forbidden` column.

---

## 5. Bonus SCORING

| Bonus | File | Log / manifest |
|-------|------|----------------|
| Pydantic validate (+2) | `quality/cleaned_schema.py` | manifest `pydantic_validate rows=49 errors=0` |
| Freshness 2+ boundary (+1) | `monitoring/freshness_check.py` | `freshness_boundaries`: data_ingest, data_publish, pipeline_latency |

## 6. Phase 1–3 & hạn chế

**Đã làm:** sort-before-dedupe, collapse token lặp, quarantine_reason_counts, canonical SLA merge, eval re-rank, unit tests (`tests/test_improvements.py` — 7 pass).

**Hạn chế còn lại:**

- Tắt `FRESHNESS_ALIGN_STALE_SNAPSHOT` sẽ báo FAIL nếu upstream không gửi export mới trong SLA.
- Debug `--no-doc-scope --no-rerank` có thể hạ chất lượng retrieval (20/21 vector-only).
