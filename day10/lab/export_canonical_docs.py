#!/usr/bin/env python3
"""Xuất data/docs/*.txt → CSV cleaned (cùng schema cleaned_lab-final.csv)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from transform.cleaning_rules import (
    _canonical_sources_from_contract,
    build_canonical_cleaned_rows,
    write_cleaned_csv,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "data" / "docs" / "cleaned"


def main() -> int:
    p = argparse.ArgumentParser(description="Export canonical .txt docs to cleaned CSV")
    p.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT),
        help="Thư mục output (mặc định: data/docs/cleaned/)",
    )
    p.add_argument(
        "--exported-at",
        default="",
        help="ISO timestamp cho cột exported_at (mặc định: UTC now)",
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    exported_at = (args.exported_at or "").strip() or datetime.now(timezone.utc).isoformat()

    all_rows = build_canonical_cleaned_rows(exported_at=exported_at)
    all_path = out_dir / "canonical_all.csv"
    write_cleaned_csv(all_path, all_rows)
    print(f"Wrote {all_path} ({len(all_rows)} chunks)")

    for doc_id, _rel in _canonical_sources_from_contract():
        rows = build_canonical_cleaned_rows(exported_at=exported_at, doc_ids=[doc_id])
        doc_path = out_dir / f"{doc_id}.csv"
        write_cleaned_csv(doc_path, rows)
        print(f"Wrote {doc_path} ({len(rows)} chunks)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
