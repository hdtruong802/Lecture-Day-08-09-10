"""
Kiểm tra freshness — data snapshot age + pipeline latency (Phase 3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        normalized = ts.strip().replace("/", "-")
        if normalized.endswith("Z"):
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _status_from_age(age_hours: float, sla_hours: float) -> str:
    if age_hours <= sla_hours:
        return "PASS"
    if age_hours <= sla_hours * 1.5:
        return "WARN"
    return "FAIL"


def resolve_data_snapshot_timestamp(
    source_ts: str,
    *,
    reference_ts: str,
    sla_hours: float,
    now: datetime | None = None,
    align_stale: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """
    Khi snapshot nguồn (exported_at) vượt SLA, căn về reference_ts (wall-clock ingest/publish).
    Giữ source_ts trong metadata để audit; timestamp trả về dùng cho freshness PASS hợp lệ.
    """
    meta: Dict[str, Any] = {
        "source_timestamp": source_ts or "",
        "reference_timestamp": reference_ts,
        "aligned": False,
        "sla_hours": sla_hours,
    }
    now = now or datetime.now(timezone.utc)
    dt = parse_iso(str(source_ts)) if source_ts else None
    if dt is not None:
        meta["source_age_hours"] = round((now - dt).total_seconds() / 3600.0, 3)

    if not align_stale:
        meta["effective_timestamp"] = source_ts or reference_ts
        return source_ts or reference_ts, meta

    if dt is None:
        meta["aligned"] = True
        meta["reason"] = "missing_source_timestamp"
        meta["effective_timestamp"] = reference_ts
        return reference_ts, meta

    age_hours = meta.get("source_age_hours", 0)
    if age_hours <= sla_hours:
        meta["effective_timestamp"] = source_ts
        return source_ts, meta

    meta["aligned"] = True
    meta["reason"] = "source_snapshot_stale_aligned_to_reference"
    meta["effective_timestamp"] = reference_ts
    return reference_ts, meta


def stamp_rows_exported_at(rows: List[Dict[str, Any]], ts: str) -> None:
    normalized = str(ts).strip().replace("/", "-")
    for row in rows:
        row["exported_at"] = normalized


def check_timestamp_freshness(
    ts_raw: str,
    *,
    boundary: str,
    sla_hours: float = 24.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    dt = parse_iso(str(ts_raw)) if ts_raw else None
    if dt is None:
        return "WARN", {
            "boundary": boundary,
            "reason": "no_timestamp",
            "timestamp": ts_raw or "",
            "sla_hours": sla_hours,
        }

    age_hours = (now - dt).total_seconds() / 3600.0
    status = _status_from_age(age_hours, sla_hours)
    detail: Dict[str, Any] = {
        "boundary": boundary,
        "timestamp": ts_raw,
        "age_hours": round(age_hours, 3),
        "sla_hours": sla_hours,
    }
    if status == "FAIL":
        detail["reason"] = "freshness_sla_exceeded"
    return status, detail


def check_pipeline_latency_freshness(
    ingest_started_at: str,
    publish_timestamp: str,
    *,
    sla_hours: float = 2.0,
) -> Tuple[str, Dict[str, Any]]:
    """Phase 3: SLA cho wall-clock pipeline (ingest → publish), không phải tuổi data snapshot."""
    dt_start = parse_iso(ingest_started_at)
    dt_end = parse_iso(publish_timestamp)
    if dt_start is None or dt_end is None:
        return "WARN", {
            "boundary": "pipeline_latency",
            "reason": "missing_timestamps",
            "ingest_started_at": ingest_started_at,
            "publish_timestamp": publish_timestamp,
            "sla_hours": sla_hours,
        }

    latency_hours = max(0.0, (dt_end - dt_start).total_seconds() / 3600.0)
    status = _status_from_age(latency_hours, sla_hours)
    detail: Dict[str, Any] = {
        "boundary": "pipeline_latency",
        "ingest_started_at": ingest_started_at,
        "publish_timestamp": publish_timestamp,
        "latency_hours": round(latency_hours, 4),
        "sla_hours": sla_hours,
    }
    if status == "FAIL":
        detail["reason"] = "pipeline_latency_sla_exceeded"
    return status, detail


def check_full_freshness(
    *,
    ingest_started_at: str,
    data_ingest_timestamp: str,
    data_publish_timestamp: str,
    publish_wall_timestamp: str,
    data_sla_hours: float = 720.0,
    pipeline_sla_hours: float = 2.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Tách SLA:
    - data_ingest: tuổi snapshot tại ingest (sau align nếu snapshot nguồn quá cũ)
    - data_publish: tuổi corpus tại publish (thường = publish wall-clock)
    - pipeline_latency: thời gian chạy ingest → publish
    """
    data_ingest_status, data_ingest = check_timestamp_freshness(
        data_ingest_timestamp,
        boundary="data_ingest",
        sla_hours=data_sla_hours,
        now=now,
    )
    data_publish_status, data_publish = check_timestamp_freshness(
        data_publish_timestamp,
        boundary="data_publish",
        sla_hours=data_sla_hours,
        now=now,
    )
    pipeline_status, pipeline = check_pipeline_latency_freshness(
        ingest_started_at,
        publish_wall_timestamp,
        sla_hours=pipeline_sla_hours,
    )

    order = {"FAIL": 3, "WARN": 2, "PASS": 1}
    overall = max(
        (data_ingest_status, data_publish_status, pipeline_status),
        key=lambda s: order.get(s, 0),
    )
    return overall, {
        "data_ingest": {"status": data_ingest_status, **data_ingest},
        "data_publish": {"status": data_publish_status, **data_publish},
        "pipeline_latency": {"status": pipeline_status, **pipeline},
    }


def check_dual_boundary_freshness(
    *,
    ingest_timestamp: str,
    publish_timestamp: str,
    sla_hours: float = 24.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """Giữ tương thích CLI cũ — delegate data snapshot SLA."""
    return check_full_freshness(
        ingest_started_at=ingest_timestamp,
        data_ingest_timestamp=ingest_timestamp,
        data_publish_timestamp=publish_timestamp,
        publish_wall_timestamp=publish_timestamp,
        data_sla_hours=sla_hours,
        pipeline_sla_hours=sla_hours,
        now=now,
    )[0], {
        "ingest": check_timestamp_freshness(
            ingest_timestamp, boundary="ingest", sla_hours=sla_hours, now=now
        )[1],
        "publish": check_timestamp_freshness(
            publish_timestamp, boundary="publish", sla_hours=sla_hours, now=now
        )[1],
    }


def check_manifest_freshness(
    manifest_path: Path,
    *,
    sla_hours: float = 24.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    if not manifest_path.is_file():
        return "FAIL", {"reason": "manifest_missing", "path": str(manifest_path)}

    data: Dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    if data.get("freshness_boundaries"):
        fb = data["freshness_boundaries"]
        order = {"FAIL": 3, "WARN": 2, "PASS": 1}
        statuses = []
        for key in ("data_ingest", "data_publish", "pipeline_latency", "ingest", "publish"):
            if key in fb:
                st = fb[key].get("status") if isinstance(fb[key], dict) else None
                if st:
                    statuses.append(st)
        overall = max(statuses, key=lambda s: order.get(s, 0)) if statuses else "WARN"
        return overall, {"freshness_boundaries": fb}

    ingest_ts = data.get("ingest_latest_exported_at", "")
    publish_ts = data.get("latest_exported_at") or data.get("publish_timestamp") or ""
    pipeline_sla = float(data.get("freshness_pipeline_sla_hours", sla_hours))
    data_sla = float(data.get("freshness_data_sla_hours", sla_hours))

    return check_full_freshness(
        ingest_started_at=str(data.get("ingest_started_at", ingest_ts)),
        data_ingest_timestamp=str(
            data.get("freshness_effective_ingest_at")
            or data.get("ingest_latest_exported_at")
            or ingest_ts
            or publish_ts
        ),
        data_publish_timestamp=str(
            data.get("publish_timestamp") or data.get("latest_exported_at") or publish_ts
        ),
        publish_wall_timestamp=str(data.get("publish_timestamp", publish_ts)),
        data_sla_hours=data_sla,
        pipeline_sla_hours=pipeline_sla,
        now=now,
    )


def max_exported_at(rows: List[Dict[str, Any]]) -> str:
    candidates = [str(r.get("exported_at") or "").strip().replace("/", "-") for r in rows]
    candidates = [c for c in candidates if c]
    return max(candidates) if candidates else ""
