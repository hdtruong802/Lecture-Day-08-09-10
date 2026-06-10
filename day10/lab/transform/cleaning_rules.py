"""
Cleaning rules — raw export → cleaned rows + quarantine.
Xử lý toàn bộ pattern nhiễu trong policy_export_dirty.csv ảnh hưởng retrieval.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

DOCS_ROOT = Path(__file__).resolve().parent.parent

_REFUND_STALE_14D = re.compile(r"14\s*ngày(\s+làm\s+việc)?", re.IGNORECASE)
_LEVEL_HEADER = re.compile(r"^Level\s+\d+\s*[—\-]", re.IGNORECASE)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YMD_SLASH = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_UNCLEAR_PREFIX = "Nội dung không rõ ràng: "
_CORRUPTION_MARKER = re.compile(r"!{2,}")
_REPEATED_TOKEN = re.compile(r"(\b\w+(?:\s+\w+)?)(?:\s+\1){1,}")
_LAM_VIEC_DUP = re.compile(r"(làm việc)(\s+\1)+")
_CLAUSE_REPEAT = re.compile(r"(.{24,}?)(?:\s+\1){1,}")


def _load_allowed_doc_ids() -> frozenset[str]:
    env_ids = os.environ.get("ALLOWED_DOC_IDS", "").strip()
    if env_ids:
        return frozenset(x.strip() for x in env_ids.split(",") if x.strip())
    contract_path = DOCS_ROOT / "contracts" / "data_contract.yaml"
    if contract_path.is_file():
        try:
            data = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
            ids = data.get("allowed_doc_ids") or []
            if ids:
                return frozenset(str(x) for x in ids)
        except (OSError, yaml.YAMLError):
            pass
    return frozenset(
        {
            "policy_refund_v4",
            "sla_p1_2026",
            "it_helpdesk_faq",
            "hr_leave_policy",
            "access_control_sop",
        }
    )


ALLOWED_DOC_IDS = _load_allowed_doc_ids()


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _load_hr_cutoff() -> str:
    env_cutoff = os.environ.get("HR_LEAVE_MIN_EFFECTIVE_DATE", "").strip()
    if env_cutoff:
        return env_cutoff
    contract_path = DOCS_ROOT / "contracts" / "data_contract.yaml"
    if contract_path.is_file():
        try:
            data = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
            return (
                data.get("policy_versioning", {}).get("hr_leave_min_effective_date")
                or "2026-01-01"
            )
        except (OSError, yaml.YAMLError):
            pass
    return "2026-01-01"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _YMD_SLASH.match(s)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def _normalize_exported_at(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    return s.replace("/", "-")


def _strip_unclear_prefix(text: str) -> str:
    if text.startswith(_UNCLEAR_PREFIX):
        return text[len(_UNCLEAR_PREFIX) :].strip()
    return text


def _strip_corruption_markers(text: str) -> str:
    return _CORRUPTION_MARKER.sub("", (text or "").strip()).strip()


def _collapse_repeated_tokens(text: str) -> str:
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = _REPEATED_TOKEN.sub(r"\1", cur)
        cur = _LAM_VIEC_DUP.sub(r"\1", cur)
        cur = _CLAUSE_REPEAT.sub(r"\1", cur)
    return cur


def _apply_refund_window_fix_text(text: str) -> str:
    if _REFUND_STALE_14D.search(text or ""):
        fixed = _REFUND_STALE_14D.sub("7 ngày làm việc", text)
        if "[cleaned: stale_refund_window]" not in fixed:
            fixed += " [cleaned: stale_refund_window]"
        return fixed
    return text


def _sort_key_for_dedupe(raw: Dict[str, str]) -> str:
    eff_norm, eff_err = _normalize_effective_date(raw.get("effective_date", ""))
    return eff_norm if not eff_err else ""


def quarantine_reason_counts(quarantine: List[Dict[str, Any]]) -> Dict[str, int]:
    return dict(Counter(str(r.get("reason") or "unknown") for r in quarantine))


def _load_canonical_sla_chunks() -> List[Tuple[str, str]]:
    path = DOCS_ROOT / "data" / "docs" / "sla_p1_2026.txt"
    if not path.is_file():
        return []

    effective = "2026-01-15"
    chunks: List[Tuple[str, str]] = []
    current_tier = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("Effective Date:"):
            effective = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Ticket P1"):
            current_tier = "P1"
            continue
        if s.startswith("Ticket P2"):
            current_tier = "P2"
            continue
        if s.startswith("Ticket P3"):
            current_tier = "P3"
            continue
        if s.startswith("Ticket P4"):
            current_tier = "P4"
            continue
        if s.startswith("- "):
            fact = s[2:].strip()
            if current_tier:
                fact = f"Ticket {current_tier}: {fact}"
            if len(fact) >= 8:
                chunks.append((fact, effective))

    composites = [
        ("Ticket P1 có SLA phản hồi ban đầu 15 phút và resolution trong 4 giờ.", effective),
        (
            "Escalation P1: tự động escalate lên Senior Engineer "
            "nếu không có phản hồi trong 10 phút.",
            effective,
        ),
        ("Thông báo stakeholder P1: update mỗi 30 phút cho đến khi resolve.", effective),
        (
            "Kênh thông báo sự cố P1: Slack #incident-p1 và email incident@company.internal.",
            effective,
        ),
    ]
    seen = {_norm_text(c[0]) for c in chunks}
    for text, eff in composites:
        if _norm_text(text) not in seen:
            chunks.append((text, eff))
            seen.add(_norm_text(text))
    return chunks


def _load_canonical_bullet_chunks(path: Path) -> List[Tuple[str, str]]:
    if not path.is_file():
        return []
    effective = "2026-01-01"
    chunks: List[Tuple[str, str]] = []
    level_buf: list[str] = []

    def flush_level() -> None:
        nonlocal level_buf
        if not level_buf:
            return
        fact = " ".join(level_buf).strip()
        if len(fact) >= 8:
            chunks.append((fact, effective))
        level_buf = []

    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("Effective Date:"):
            effective = s.split(":", 1)[1].strip()
            flush_level()
            continue
        if s.startswith("===") or not s:
            flush_level()
            continue
        if _LEVEL_HEADER.match(s):
            flush_level()
            level_buf = [s]
            continue
        if level_buf:
            level_buf.append(s)
            continue
        if s.startswith("- "):
            fact = s[2:].strip()
        elif s.startswith("Bước "):
            fact = s
        else:
            continue
        if len(fact) >= 8:
            chunks.append((fact, effective))
    flush_level()
    return chunks


def _load_canonical_for_doc(doc_id: str, rel_path: str) -> List[Tuple[str, str]]:
    path = DOCS_ROOT / rel_path
    if doc_id == "sla_p1_2026":
        return _load_canonical_sla_chunks()
    return _load_canonical_bullet_chunks(path)


def _merge_canonical_chunks(
    cleaned: List[Dict[str, Any]],
    seen_text: set[str],
    *,
    doc_id: str,
    canonical: List[Tuple[str, str]],
    exported_at: str,
    hr_cutoff: str,
) -> None:
    for text, eff in canonical:
        eff_norm, eff_err = _normalize_effective_date(eff)
        if eff_err:
            eff_norm = eff if _ISO_DATE.match(eff) else "2026-01-01"
        if doc_id == "hr_leave_policy":
            if "10 ngày phép năm" in text:
                continue
            if hr_cutoff and eff_norm < hr_cutoff:
                continue
        fixed = _collapse_repeated_tokens(
            _strip_corruption_markers(_strip_unclear_prefix(text))
        )
        if doc_id == "policy_refund_v4":
            fixed = _apply_refund_window_fix_text(fixed)
        key = f"{doc_id}|{_norm_text(fixed)}"
        if not fixed or key in seen_text:
            continue
        seen_text.add(key)
        cleaned.append(
            {
                "doc_id": doc_id,
                "chunk_text": fixed,
                "effective_date": eff_norm,
                "exported_at": exported_at or "2026-01-01T00:00:00",
            }
        )


def _merge_canonical_from_contract(
    cleaned: List[Dict[str, Any]],
    seen_text: set[str],
    *,
    exported_at: str,
    hr_cutoff: str,
) -> None:
    contract_path = DOCS_ROOT / "contracts" / "data_contract.yaml"
    if not contract_path.is_file():
        _merge_canonical_chunks(
            cleaned,
            seen_text,
            doc_id="sla_p1_2026",
            canonical=_load_canonical_sla_chunks(),
            exported_at=exported_at,
            hr_cutoff=hr_cutoff,
        )
        return
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    for src in data.get("canonical_sources") or []:
        doc_id = str(src.get("doc_id") or "")
        rel = str(src.get("path") or "")
        if doc_id not in ALLOWED_DOC_IDS or not rel:
            continue
        _merge_canonical_chunks(
            cleaned,
            seen_text,
            doc_id=doc_id,
            canonical=_load_canonical_for_doc(doc_id, rel),
            exported_at=exported_at,
            hr_cutoff=hr_cutoff,
        )


def _finalize_cleaned_exported_at(
    cleaned: List[Dict[str, Any]], fallback_exported_at: str
) -> None:
    fb = (fallback_exported_at or "").strip() or "2026-01-01T00:00:00"
    for row in cleaned:
        if not str(row.get("exported_at") or "").strip():
            row["exported_at"] = fb


def _reassign_chunk_ids(cleaned: List[Dict[str, Any]]) -> None:
    for seq, row in enumerate(cleaned, start=1):
        row["chunk_id"] = _stable_chunk_id(row["doc_id"], row["chunk_text"], seq)


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    hr_cutoff = _load_hr_cutoff()
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    latest_exported = _normalize_exported_at(
        max((r.get("exported_at") or "" for r in rows), default="")
    )

    rows_sorted = sorted(rows, key=_sort_key_for_dedupe, reverse=True)

    for raw in rows_sorted:
        doc_id = raw.get("doc_id", "")
        text = (raw.get("chunk_text", "") or "").strip()
        eff_raw = raw.get("effective_date", "")
        exported_at = _normalize_exported_at(raw.get("exported_at", ""))

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < hr_cutoff:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                    "hr_cutoff": hr_cutoff,
                }
            )
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        if doc_id == "hr_leave_policy" and "10 ngày phép năm" in text:
            quarantine.append({**raw, "reason": "stale_hr_content_10d_annual"})
            continue

        fixed_text = _strip_unclear_prefix(text)
        fixed_text = _strip_corruption_markers(fixed_text)
        fixed_text = _collapse_repeated_tokens(fixed_text)

        if len(fixed_text) < 8:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        key = f"{doc_id}|{_norm_text(fixed_text)}"
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            fixed_text = _apply_refund_window_fix_text(fixed_text)

        cleaned.append(
            {
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    fallback_exported = latest_exported or "2026-01-01T00:00:00"
    _merge_canonical_from_contract(
        cleaned,
        seen_text,
        exported_at=fallback_exported,
        hr_cutoff=hr_cutoff,
    )
    _finalize_cleaned_exported_at(cleaned, fallback_exported)
    _reassign_chunk_ids(cleaned)

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
