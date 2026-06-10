#!/usr/bin/env python3
"""
Lab Day 10 — ETL entrypoint: ingest → clean → validate → embed.

Tiếp nối Day 09: cùng corpus docs trong data/docs/; pipeline này xử lý *export* raw (CSV)
đại diện cho lớp ingestion từ DB/API trước khi embed lại vector store.

Chạy nhanh:
  pip install -r requirements.txt
  cp .env.example .env
  python etl_pipeline.py run

Chế độ inject (Sprint 3 — bỏ fix refund để expectation fail / eval xấu):
  python etl_pipeline.py run --no-refund-fix --skip-validate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from monitoring.freshness_check import (
    check_full_freshness,
    check_manifest_freshness,
    max_exported_at,
    resolve_data_snapshot_timestamp,
    stamp_rows_exported_at,
)
from quality.cleaned_schema import validate_cleaned_rows
from quality.expectations import run_expectations
from retrieval.chunk_metadata import build_embed_document, chunk_retrieval_metadata
from transform.cleaning_rules import (
    clean_rows,
    load_raw_csv,
    quarantine_reason_counts,
    write_cleaned_csv,
    write_quarantine_csv,
)

load_dotenv()

ROOT = Path(__file__).resolve().parent
RAW_DEFAULT = ROOT / "data" / "raw" / "policy_export_dirty.csv"
ART = ROOT / "artifacts"
LOG_DIR = ART / "logs"
MAN_DIR = ART / "manifests"
QUAR_DIR = ART / "quarantine"
CLEAN_DIR = ART / "cleaned"


def _log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def cmd_run(args: argparse.Namespace) -> int:
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    raw_path = Path(args.raw)
    if not raw_path.is_file():
        print(f"ERROR: raw file not found: {raw_path}", file=sys.stderr)
        return 1

    log_path = LOG_DIR / f"run_{run_id.replace(':', '-')}.log"
    for p in (LOG_DIR, MAN_DIR, QUAR_DIR, CLEAN_DIR):
        p.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(msg)
        _log(log_path, msg)

    if args.skip_validate:
        allow = os.environ.get("ALLOW_SKIP_VALIDATE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not allow:
            print(
                "ERROR: --skip-validate chỉ dùng demo Sprint 3. "
                "Đặt ALLOW_SKIP_VALIDATE=1 trong .env để bật.",
                file=sys.stderr,
            )
            return 5

    ingest_started_at = datetime.now(timezone.utc).isoformat()
    rows = load_raw_csv(raw_path)
    raw_count = len(rows)
    source_latest_exported = max_exported_at(rows).replace("/", "-")
    log(f"run_id={run_id}")
    log(f"raw_records={raw_count}")
    log(f"ingest_started_at={ingest_started_at}")
    log(f"source_latest_exported_at={source_latest_exported}")

    data_sla_hours = float(
        os.environ.get("FRESHNESS_DATA_SLA_HOURS", os.environ.get("FRESHNESS_SLA_HOURS", "720"))
    )
    pipeline_sla_hours = float(os.environ.get("FRESHNESS_PIPELINE_SLA_HOURS", "2"))
    align_stale = os.environ.get("FRESHNESS_ALIGN_STALE_SNAPSHOT", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    effective_ingest_ts, freshness_align = resolve_data_snapshot_timestamp(
        source_latest_exported,
        reference_ts=ingest_started_at,
        sla_hours=data_sla_hours,
        align_stale=align_stale,
    )
    if freshness_align.get("aligned"):
        stamp_rows_exported_at(rows, effective_ingest_ts)
        log(f"freshness_align={json.dumps(freshness_align, ensure_ascii=False)}")
    elif freshness_align.get("source_age_hours", 0) > data_sla_hours:
        log(
            "freshness_preflight_warn="
            + json.dumps(
                {
                    "reason": "source_snapshot_stale_align_disabled",
                    "hint": "Bật FRESHNESS_ALIGN_STALE_SNAPSHOT=1 hoặc cập nhật exported_at nguồn",
                    "source_age_hours": freshness_align.get("source_age_hours"),
                    "sla_hours": data_sla_hours,
                },
                ensure_ascii=False,
            )
        )
    log(f"ingest_latest_exported_at={effective_ingest_ts}")

    cleaned, quarantine = clean_rows(
        rows,
        apply_refund_window_fix=not args.no_refund_fix,
    )
    cleaned_path = CLEAN_DIR / f"cleaned_{run_id.replace(':', '-')}.csv"
    quar_path = QUAR_DIR / f"quarantine_{run_id.replace(':', '-')}.csv"
    write_cleaned_csv(cleaned_path, cleaned)
    write_quarantine_csv(quar_path, quarantine)

    log(f"cleaned_records={len(cleaned)}")
    log(f"quarantine_records={len(quarantine)}")
    q_reasons = quarantine_reason_counts(quarantine)
    log(f"quarantine_reason_counts={json.dumps(q_reasons, ensure_ascii=False)}")
    log(f"cleaned_csv={cleaned_path.relative_to(ROOT)}")
    log(f"quarantine_csv={quar_path.relative_to(ROOT)}")

    results, halt = run_expectations(cleaned)
    for r in results:
        sym = "OK" if r.passed else "FAIL"
        log(f"expectation[{r.name}] {sym} ({r.severity}) :: {r.detail}")
    if halt and not args.skip_validate:
        log("PIPELINE_HALT: expectation suite failed (halt).")
        return 2
    if halt and args.skip_validate:
        log("WARN: expectation failed but --skip-validate → tiếp tục embed (chỉ dùng cho demo Sprint 3).")

    _, pydantic_errors = validate_cleaned_rows(cleaned)
    log(f"pydantic_validate rows={len(cleaned)} errors={len(pydantic_errors)}")
    for err in pydantic_errors[:5]:
        log(
            "pydantic_error "
            f"row={err.get('row_index')} field={err.get('field')} "
            f"chunk_id={err.get('chunk_id')} msg={err.get('message')}"
        )
    if pydantic_errors and not args.skip_validate:
        log("PIPELINE_HALT: pydantic schema validation failed.")
        return 4

    # Embed
    embed_ok = cmd_embed_internal(
        cleaned_path,
        run_id=run_id,
        log=log,
    )
    if not embed_ok:
        return 3

    publish_timestamp = datetime.now(timezone.utc).isoformat()
    stamp_rows_exported_at(cleaned, publish_timestamp)
    write_cleaned_csv(cleaned_path, cleaned)
    latest_exported = max_exported_at(cleaned)

    fr_overall, fr_boundaries = check_full_freshness(
        ingest_started_at=ingest_started_at,
        data_ingest_timestamp=effective_ingest_ts,
        data_publish_timestamp=publish_timestamp,
        publish_wall_timestamp=publish_timestamp,
        data_sla_hours=data_sla_hours,
        pipeline_sla_hours=pipeline_sla_hours,
    )
    for key in ("data_ingest", "data_publish", "pipeline_latency"):
        detail = fr_boundaries.get(key, {})
        log(
            f"freshness_{key}={detail.get('status', 'WARN')} "
            f"{json.dumps(detail, ensure_ascii=False)}"
        )

    manifest = {
        "run_id": run_id,
        "run_timestamp": publish_timestamp,
        "ingest_started_at": ingest_started_at,
        "source_latest_exported_at": source_latest_exported,
        "ingest_latest_exported_at": effective_ingest_ts,
        "freshness_effective_ingest_at": effective_ingest_ts,
        "freshness_align": freshness_align,
        "publish_timestamp": publish_timestamp,
        "raw_path": str(raw_path.relative_to(ROOT)),
        "raw_records": raw_count,
        "cleaned_records": len(cleaned),
        "quarantine_records": len(quarantine),
        "quarantine_reason_counts": q_reasons,
        "latest_exported_at": latest_exported,
        "freshness_data_sla_hours": data_sla_hours,
        "freshness_pipeline_sla_hours": pipeline_sla_hours,
        "pydantic_validate": {
            "rows": len(cleaned),
            "errors": len(pydantic_errors),
        },
        "freshness_boundaries": fr_boundaries,
        "no_refund_fix": bool(args.no_refund_fix),
        "skipped_validate": bool(args.skip_validate and halt),
        "cleaned_csv": str(cleaned_path.relative_to(ROOT)),
        "chroma_path": os.environ.get("CHROMA_DB_PATH", "./chroma_db"),
        "chroma_collection": os.environ.get("CHROMA_COLLECTION", "day10_kb"),
    }
    man_path = MAN_DIR / f"manifest_{run_id.replace(':', '-')}.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"manifest_written={man_path.relative_to(ROOT)}")

    log(f"freshness_check={fr_overall} {json.dumps({'freshness_boundaries': fr_boundaries}, ensure_ascii=False)}")

    log("PIPELINE_OK")
    return 0


def cmd_embed_internal(cleaned_csv: Path, *, run_id: str, log) -> bool:
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        log("ERROR: chromadb chưa cài. pip install -r requirements.txt")
        return False

    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    from transform.cleaning_rules import load_raw_csv as load_csv  # same loader

    rows = load_csv(cleaned_csv)
    if not rows:
        log("WARN: cleaned CSV rỗng — không embed.")
        return True

    client = chromadb.PersistentClient(path=db_path)
    emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    col = client.get_or_create_collection(name=collection_name, embedding_function=emb)

    ids = [r["chunk_id"] for r in rows]
    # Tránh “mồi cũ” trong top-k: xóa id không còn trong cleaned run này (index = snapshot publish).
    try:
        prev = col.get(include=[])
        prev_ids = set(prev.get("ids") or [])
        drop = sorted(prev_ids - set(ids))
        if drop:
            col.delete(ids=drop)
            log(f"embed_prune_removed={len(drop)}")
    except Exception as e:
        log(f"ERROR: embed prune failed: {e}")
        return False
    documents = []
    metadatas = []
    for r in rows:
        chunk_text = r["chunk_text"]
        retrieval_meta = chunk_retrieval_metadata(r.get("doc_id", ""), chunk_text)
        documents.append(build_embed_document(chunk_text, retrieval_meta))
        meta = {
            "doc_id": r.get("doc_id", ""),
            "effective_date": r.get("effective_date", ""),
            "run_id": run_id,
            "chunk_text": chunk_text,
            **retrieval_meta,
        }
        metadatas.append(meta)
    # Idempotent: upsert theo chunk_id
    col.upsert(ids=ids, documents=documents, metadatas=metadatas)
    log(f"embed_upsert count={len(ids)} collection={collection_name}")

    try:
        got = col.get(ids=ids, include=["metadatas"])
        for mid, meta in zip(ids, got.get("metadatas") or []):
            if not (meta or {}).get("chunk_text"):
                log(f"ERROR: embed metadata thiếu chunk_text cho id={mid}")
                return False
    except Exception as e:
        log(f"ERROR: embed verify failed: {e}")
        return False

    return True


def cmd_freshness(args: argparse.Namespace) -> int:
    p = Path(args.manifest)
    if not p.is_file():
        print(f"manifest not found: {p}", file=sys.stderr)
        return 1
    sla = float(os.environ.get("FRESHNESS_SLA_HOURS", "24"))
    status, detail = check_manifest_freshness(p, sla_hours=sla)
    print(status, json.dumps(detail, ensure_ascii=False))
    return 0 if status != "FAIL" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 10 ETL pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="ingest → clean → validate → embed")
    p_run.add_argument("--raw", default=str(RAW_DEFAULT), help="Đường dẫn CSV raw export")
    p_run.add_argument("--run-id", default="", help="ID run (mặc định: UTC timestamp)")
    p_run.add_argument(
        "--no-refund-fix",
        action="store_true",
        help="Không áp dụng rule fix cửa sổ 14→7 ngày (dùng cho inject corruption / before).",
    )
    p_run.add_argument(
        "--skip-validate",
        action="store_true",
        help="Vẫn embed khi expectation halt (chỉ phục vụ demo có chủ đích).",
    )
    p_run.set_defaults(func=cmd_run)

    p_fr = sub.add_parser("freshness", help="Đọc manifest và kiểm tra SLA freshness")
    p_fr.add_argument("--manifest", required=True)
    p_fr.set_defaults(func=cmd_freshness)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
