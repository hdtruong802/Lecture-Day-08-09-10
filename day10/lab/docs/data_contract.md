# Data contract — Lab Day 10

> Đồng bộ với [`contracts/data_contract.yaml`](../contracts/data_contract.yaml)

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| policy_refund_v4 | CSV export ERP | Chunk stale "14 ngày làm việc" | `refund_no_stale_14d_window` halt; eval `hits_forbidden` |
| sla_p1_2026 | CSV export ticketing | Chunk P1 thiếu dòng escalation | `contains_expected` false trên câu P1 escalation |
| it_helpdesk_faq | CSV export KB | doc_id lạ / chunk rỗng | `quarantine_records` reason `unknown_doc_id` |
| hr_leave_policy | CSV export HRIS | Xung đột 10 vs 12 ngày phép | `stale_hr_content_10d_annual`; E6/E8 |
| access_control_sop | CSV export IAM (mới thêm) | Không có trong allowlist baseline | `access_control_sop_min_one_chunk` halt |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| chunk_id | string | Có | SHA256 16 ký tự + doc_id + seq |
| doc_id | string | Có | Một trong 5 allowlist |
| chunk_text | string | Có | min 8 ký tự sau clean |
| effective_date | date | Có | ISO YYYY-MM-DD |
| exported_at | datetime | Có | Chuẩn hoá slash → hyphen |

---

## 3. Quy tắc quarantine vs drop

- Record lỗi → `artifacts/quarantine/quarantine_<run_id>.csv` kèm `reason`.
- Không drop im lặng: mọi row raw đều accounted (cleaned + quarantine = raw sau dedupe logic).
- Merge lại: cần owner Cleaning review quarantine và sửa nguồn upstream.

---

## 4. Phiên bản & canonical

| doc_id | Source of truth | Versioning |
|--------|-----------------|------------|
| policy_refund_v4 | `data/docs/policy_refund_v4.txt` | Cửa sổ 7 ngày làm việc (v4) |
| hr_leave_policy | `data/docs/hr_leave_policy.txt` | Cutoff `2026-01-01` đọc từ contract/env |
| access_control_sop | `data/docs/access_control_sop.txt` | Level 4 = IT Manager + CISO |
