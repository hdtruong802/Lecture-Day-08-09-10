#!/usr/bin/env python3
"""
Gate nộp bài — chạy trước khi commit artifact.

  python pre_submit_check.py
  python pre_submit_check.py --run-id lab-final
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def check_eval_csv(path: Path, expected: int) -> tuple[int, list[str]]:
    msgs: list[str] = []
    if not path.is_file():
        return 1, [f"MISSING eval CSV: {path}"]
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    pass_n = sum(
        1
        for r in rows
        if r.get("contains_expected") == "yes" and r.get("hits_forbidden") == "no"
    )
    msgs.append(f"eval_csv pass={pass_n}/{len(rows)} ({path.name})")
    if pass_n < expected:
        msgs.append(f"FAIL: eval cần >={expected} pass, got {pass_n}")
        return 1, msgs
    return 0, msgs


def check_manifest_freshness(path: Path) -> tuple[int, list[str]]:
    msgs: list[str] = []
    if not path.is_file():
        return 1, [f"MISSING manifest: {path}"]
    data = json.loads(path.read_text(encoding="utf-8"))
    fb = data.get("freshness_boundaries") or {}
    overall = "PASS"
    for key in ("data_ingest", "data_publish", "pipeline_latency"):
        st = (fb.get(key) or {}).get("status", "WARN")
        msgs.append(f"freshness[{key}]={st}")
        if st == "FAIL":
            overall = "FAIL"
    if overall != "PASS":
        msgs.append("FAIL: freshness_boundaries chưa PASS — chạy lại pipeline chuẩn")
        return 1, msgs
    msgs.append(f"OK manifest run_id={data.get('run_id')}")
    return 0, msgs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="lab-final")
    p.add_argument("--eval-expected", type=int, default=21)
    args = p.parse_args()

    code = 0
    if _run([sys.executable, "-m", "pytest", "tests/", "-q"]) != 0:
        return 1

    manifest = ROOT / "artifacts" / "manifests" / f"manifest_{args.run_id}.json"
    grading = ROOT / "artifacts" / "eval" / "grading_run.jsonl"
    eval_csv = ROOT / "artifacts" / "eval" / "after_fix_eval.csv"

    c1, m1 = check_manifest_freshness(manifest)
    code = max(code, c1)
    for m in m1:
        print(m)

    c2, m2 = check_eval_csv(eval_csv, args.eval_expected)
    code = max(code, c2)
    for m in m2:
        print(m)

    c3 = _run(
        [
            sys.executable,
            "instructor_quick_check.py",
            "--grading",
            str(grading),
            "--manifest",
            str(manifest),
            "--eval-csv",
            str(eval_csv),
        ]
    )
    code = max(code, c3)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
