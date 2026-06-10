# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Data Observability

**Họ và tên:** Hoàng Đức Trường  
**Mã học viên:** 2A202600552  
**Vai trò:** Ingestion · Cleaning & Quality · Embed · Monitoring / Docs

**Ngày nộp:** 2026-06-10  
**Repo:** `Lecture-Day-08-09-10/day10/lab`  

---

> **Nộp tại:** `reports/report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

**Tóm tắt luồng:**

Nguồn raw là `data/raw/policy_export_dirty.csv` — export mẫu 247 dòng, 39 `doc_id`, mô phỏng 5 hệ thống nguồn kèm nhiễu `invalid_doc_*`, `legacy_*`, marker `!!!`. Pipeline: ingest → `transform/cleaning_rules.py` (strip corruption, sort-dedupe, merge canonical 5 doc từ contract) → pydantic → `quality/expectations.py` (halt) → embed Chroma `day10_kb` (metadata + prefix + prune) → manifest + freshness 3 boundary. Run chuẩn `lab-final`: `raw_records=247`, `cleaned_records=86`, `quarantine_records=212`. `run_id` trong `artifacts/logs/run_lab-final.log` và `artifacts/manifests/manifest_lab-final.json`. Grading **10/10**, eval **21/21**.

**Lệnh chạy một dòng:**

```bash
python etl_pipeline.py run --run-id lab-final && python grading_run.py --out artifacts/eval/grading_run.jsonl && python eval_retrieval.py --out artifacts/eval/after_fix_eval.csv && python pre_submit_check.py --run-id lab-final
```

---

## 2. Cleaning & expectation (150–200 từ)

### 2a. Bảng metric_impact

| Rule / Expectation mới | Trước | Sau | Chứng cứ |
|------------------------|-------|-----|----------|
| `access_control_sop` allowlist | gq_d10_10 fail | pass; 14 chunk | `grading_run.jsonl` |
| `stale_hr_content_10d_annual` | E6 halt | quarantine; E6 OK | `run_lab-final.log` |
| `_strip_corruption_markers` (!!!) | top1 có `!!!` | 0 chunk marker | E10 `corruption_marker_chunks=0` |
| merge canonical 5 doc (contract) | thiếu fact canonical | cleaned 49→86 | `cleaned_lab-final.csv` |
| E7–E10 | — | halt/warn coverage | `quality/expectations.py` |

**Expectation halt:** E1–E3, E5–E8. **Warn:** E4, E9, E10.

**Ví dụ expectation fail:** inject `--no-refund-fix --skip-validate` (cần `ALLOW_SKIP_VALIDATE=1`) → `refund_no_stale_14d_window` FAIL; khắc phục bằng pipeline chuẩn.

---

## 3. Before / after retrieval (200–250 từ)

| question_id | inject | sau fix |
|-------------|--------|---------|
| `q_refund_window` hits_forbidden | **yes** | **no** |
| `q_p1_escalation` | fail | **pass** |
| **Tổng 21 câu** | — | **21/21** |

Retrieval 3 lớp: embed prefix + metadata Chroma; doc-scope query; metadata re-rank (`priority_tier`/`sla_topic`). Chế độ `--no-rerank` (metadata-only) vẫn **21/21** nhờ doc-scope + prefix.

---

## 4. Freshness & monitoring (100–150 từ)

SLA data 720h, pipeline latency 2h. `FRESHNESS_ALIGN_STALE_SNAPSHOT=1` căn snapshot CSV cũ về ingest wall-clock; manifest giữ `source_latest_exported_at` audit. 3 boundary **PASS** trên `lab-final`. Tắt align → log `freshness_preflight_warn` hướng dẫn khắc phục.

---

## 5. Liên hệ Day 09 (50–100 từ)

Corpus validated trong `day10_kb`. Day 09 agent trỏ `CHROMA_COLLECTION=day10_kb` để retrieval đọc chunk đã clean — refund 7 ngày, HR 12 ngày, SLA P1, access Level 4. Canonical tại `data/docs/`.

---

## 6. Đánh giá rủi ro & biện pháp đã xử lý

### 6a. Rủi ro đã liệt kê trước đó — trạng thái

| Rủi ro | Mức | Biện pháp | Trạng thái |
|--------|-----|-----------|------------|
| Snapshot CSV cũ → freshness FAIL | Cao | `FRESHNESS_ALIGN_STALE_SNAPSHOT` + preflight warn khi tắt | **Đã xử lý** — PASS |
| Re-rank keyword ad-hoc / P2 trước P1 | Cao | Metadata embed + doc-scope + `retrieval/rerank.py` | **Đã xử lý** — 21/21 |
| `--no-doc-scope --no-rerank` debug | Thấp | Giữ flag debug; mặc định bật doc-scope + rerank | **Chấp nhận** (có chủ đích) |

### 6b. Rủi ro bổ sung phát hiện thêm — trạng thái

| Rủi ro | Mức | Biện pháp | Trạng thái |
|--------|-----|-----------|------------|
| Marker `!!!` trong raw CSV lọt cleaned | Cao | `_strip_corruption_markers` + E10 warn | **Đã xử lý** |
| Thiếu chunk canonical (chỉ merge SLA) | Trung bình | `_merge_canonical_from_contract` — 5 doc | **Đã xử lý** |
| `--skip-validate` embed dữ liệu bẩn | Cao | Yêu cầu `ALLOW_SKIP_VALIDATE=1` | **Đã xử lý** |
| Vector Chroma cũ / thiếu `chunk_text` metadata | Trung bình | Prune fail → halt embed; verify sau upsert | **Đã xử lý** |
| Artifact không commit được (`.gitignore`) | Cao | `!artifacts/eval/**`, `manifests/**`, … | **Đã xử lý** |
| Nộp thiếu bằng chứng / không chạy test | Trung bình | `pre_submit_check.py` + mở rộng `instructor_quick_check.py` | **Đã xử lý** |
| Báo cáo lệch run_id / số liệu cũ | Thấp | Đồng bộ `lab-final`, cleaned=86 | **Đã xử lý** |

### 6c. Bonus SCORING (+3)

| Bonus | Điểm | Chứng cứ |
|-------|------|----------|
| Pydantic validate | +2 | manifest `pydantic_validate rows=86 errors=0` |
| Freshness 3 boundary | +1 | `freshness_boundaries` PASS |

### 6d. Gate nộp bài

```bash
python pre_submit_check.py --run-id lab-final
```

Kiểm tra: pytest 15 pass, grading 10/10, eval 21/21, manifest freshness PASS.
