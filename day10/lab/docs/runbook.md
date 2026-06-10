# Runbook — Lab Day 10

---

## Symptom

Agent / retrieval trả lời **"14 ngày làm việc"** thay vì **7 ngày** cho câu hỏi refund; hoặc HR trả **10 ngày phép** thay vì **12 ngày**; hoặc SLA P1 escalation trả **90 phút** thay vì **10 phút**.

---

## Detection

| Signal | Nơi xem |
|--------|---------|
| `expectation[refund_no_stale_14d_window] FAIL` | `artifacts/logs/run_*.log` |
| `hits_forbidden=yes` trên eval CSV | `artifacts/eval/after_*.csv` |
| `freshness_data_*=PASS` / `freshness_align` trong log | Log pipeline hoặc manifest |
| `quarantine_reason_counts` bất thường | `artifacts/manifests/manifest_<run_id>.json` |
| Eval / grading fail `contains_expected` | `eval_retrieval.py`, `grading_run.jsonl` |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Mở `artifacts/manifests/manifest_<run_id>.json` | `cleaned_records`, `quarantine_records`, `quarantine_reason_counts`, `freshness_boundaries` |
| 2 | Mở `artifacts/quarantine/quarantine_<run_id>.csv` | Lọc `reason=stale_hr_content_10d_annual` hoặc `unknown_doc_id` |
| 3 | Chạy `python eval_retrieval.py --out artifacts/eval/debug.csv` | 21/21 pass; kiểm `q_refund_window`, `q_p1_escalation` |
| 4 | Chạy `python grading_run.py` | 10 dòng JSONL, kiểm `contains_expected` / `hits_forbidden` |
| 5 | Chạy `pytest tests/test_improvements.py` | 7 tests pass (cleaning + canonical SLA) |

---

## Mitigation

1. **Refund stale:** đảm bảo `apply_refund_window_fix=True` (không dùng `--no-refund-fix`).
2. **HR conflict:** bật rule `stale_hr_content_10d_annual`; kiểm tra `HR_LEAVE_MIN_EFFECTIVE_DATE` trong contract.
3. **Access control missing:** thêm `access_control_sop` vào `ALLOWED_DOC_IDS`.
4. **Inject Sprint 3:** đặt `ALLOW_SKIP_VALIDATE=1` trong `.env` rồi mới dùng `--skip-validate`.
5. **Snapshot nguồn quá cũ:** bật `FRESHNESS_ALIGN_STALE_SNAPSHOT=1` (mặc định); nếu tắt, xem `freshness_preflight_warn` trong log.
6. **Retrieval sai doc/P1-P2:** rerun embed; mặc định doc-scope + metadata re-rank.
7. **Trước nộp bài:** `python pre_submit_check.py --run-id lab-final`.

---

## Prevention

- Giữ expectation **halt** cho refund 14d, HR 10d, access_control coverage.
- Điền bảng `metric_impact` trong report mỗi khi thêm rule.
- Freshness: `FRESHNESS_DATA_SLA_HOURS=720`, `FRESHNESS_PIPELINE_SLA_HOURS=2`, `FRESHNESS_ALIGN_STALE_SNAPSHOT=1`; đo **data_ingest**, **data_publish**, **pipeline_latency**.
- Pydantic schema halt trước embed nếu cleaned row lệch contract (`pydantic_validate errors>0`).
- Không dùng `--skip-validate` ngoài demo Sprint 3 có chủ đích.
- Chạy `pytest tests/test_improvements.py` sau khi sửa `cleaning_rules.py`.
