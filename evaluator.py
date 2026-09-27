from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


REQUIRED_FILES = {"output.csv", "manifest.json", "quality_report.json"}

REQUIRED_OUTPUT_COLUMNS = [
    "event_id",
    "trip_id",
    "stop_sequence",
    "service_date",
    "station_code",
    "station_osm_id",
    "station_name",
    "scheduled_arrival",
    "actual_arrival",
    "delay_seconds",
    "latitude",
    "longitude",
    "source_ingested_at",
]

REQUIRED_MANIFEST_FIELDS = [
    "schema_version",
    "student_or_team",
    "run_id",
    "pipeline_tool",
    "generated_at",
    "sources",
    "output_row_count",
]

REQUIRED_QUALITY_FIELDS = [
    "scheduled_input_row_count",
    "realtime_input_row_count",
    "output_row_count",
    "duplicate_records_removed",
    "duplicate_output_record_count",
    "unmatched_station_count",
    "invalid_timestamp_count",
]


@dataclass
class Check:
    name: str
    points: int
    maximum: int
    status: str
    detail: str


def _check(name: str, maximum: int, status: str, detail: str) -> Check:
    if status not in {"pass", "warning", "fail"}:
        raise ValueError(f"Unsupported status: {status}")
    points = maximum if status == "pass" else maximum // 2 if status == "warning" else 0
    return Check(name=name, points=points, maximum=maximum, status=status, detail=detail)


def _read_json(raw: bytes, filename: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{filename} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{filename} must contain a JSON object.")
    return value


def _archive_members(archive_bytes: bytes) -> dict[str, bytes]:
    if len(archive_bytes) > 25 * 1024 * 1024:
        raise ValueError("The ZIP archive exceeds the 25 MB prototype limit.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a readable ZIP archive.") from exc

    members: dict[str, bytes] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.file_size > 20 * 1024 * 1024:
            raise ValueError(f"{info.filename} exceeds the 20 MB per-file limit.")
        basename = info.filename.rsplit("/", 1)[-1]
        if basename in REQUIRED_FILES:
            members[basename] = archive.read(info)
    return members


def evaluate_submission(archive_bytes: bytes) -> dict[str, Any]:
    checks: list[Check] = []
    members = _archive_members(archive_bytes)

    missing_files = sorted(REQUIRED_FILES - members.keys())
    checks.append(
        _check(
            "Submission package",
            5,
            "pass" if not missing_files else "fail",
            "All required files are present."
            if not missing_files
            else f"Missing: {', '.join(missing_files)}",
        )
    )
    if missing_files:
        return _finish(checks, rows=0, metadata={"missing_files": missing_files})

    manifest = _read_json(members["manifest.json"], "manifest.json")
    quality = _read_json(members["quality_report.json"], "quality_report.json")
    try:
        output = pd.read_csv(io.BytesIO(members["output.csv"]), dtype={"service_date": "string"})
    except Exception as exc:
        raise ValueError(f"output.csv could not be parsed: {exc}") from exc

    missing_manifest = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
    checks.append(
        _check(
            "Manifest metadata",
            10,
            "pass" if not missing_manifest else "fail",
            "Manifest contains run identity, tooling, lineage and row-count metadata."
            if not missing_manifest
            else f"Missing manifest fields: {', '.join(missing_manifest)}",
        )
    )

    source_text = json.dumps(manifest.get("sources", []), ensure_ascii=False).lower()
    has_gtfs = "gtfs" in source_text or "nmbs" in source_text or "sncb" in source_text
    has_osm = "openstreetmap" in source_text or "open street map" in source_text or "osm" in source_text
    source_status = "pass" if has_gtfs and has_osm else "warning" if has_gtfs or has_osm else "fail"
    checks.append(
        _check(
            "Source declarations",
            5,
            source_status,
            f"GTFS/NMBS source declared: {'yes' if has_gtfs else 'no'}; OpenStreetMap source declared: {'yes' if has_osm else 'no'}.",
        )
    )

    missing_columns = [column for column in REQUIRED_OUTPUT_COLUMNS if column not in output.columns]
    checks.append(
        _check(
            "Output schema",
            15,
            "pass" if not missing_columns else "fail",
            "All required output columns are present."
            if not missing_columns
            else f"Missing columns: {', '.join(missing_columns)}",
        )
    )

    missing_quality = [field for field in REQUIRED_QUALITY_FIELDS if field not in quality]
    checks.append(
        _check(
            "Quality report",
            10,
            "pass" if not missing_quality else "fail",
            "Quality report contains the required reconciliation metrics."
            if not missing_quality
            else f"Missing quality fields: {', '.join(missing_quality)}",
        )
    )

    manifest_rows = manifest.get("output_row_count")
    quality_rows = quality.get("output_row_count")
    counts_match = manifest_rows == len(output) and quality_rows == len(output)
    checks.append(
        _check(
            "Output-count consistency",
            10,
            "pass" if counts_match else "fail",
            f"CSV={len(output)}, manifest={manifest_rows}, quality report={quality_rows}.",
        )
    )

    key_columns = ["trip_id", "service_date", "stop_sequence"]
    if all(column in output.columns for column in key_columns):
        duplicate_keys = int(output.duplicated(key_columns).sum())
    else:
        duplicate_keys = len(output)
    event_duplicates = int(output["event_id"].duplicated().sum()) if "event_id" in output.columns else len(output)
    reported_duplicates = quality.get("duplicate_output_record_count")
    unique_output = duplicate_keys == 0 and event_duplicates == 0 and reported_duplicates == 0
    checks.append(
        _check(
            "Uniqueness and duplicate control",
            10,
            "pass" if unique_output else "fail",
            f"Composite-key duplicates={duplicate_keys}; event_id duplicates={event_duplicates}; reported output duplicates={reported_duplicates}.",
        )
    )

    timestamp_columns = ["scheduled_arrival", "actual_arrival", "source_ingested_at"]
    invalid_timestamps = 0
    for column in timestamp_columns:
        if column not in output.columns:
            invalid_timestamps += len(output)
        else:
            invalid_timestamps += int(pd.to_datetime(output[column], errors="coerce", utc=True).isna().sum())
    checks.append(
        _check(
            "Timestamp validity",
            10,
            "pass" if invalid_timestamps == 0 else "fail",
            f"Invalid timestamp values: {invalid_timestamps}.",
        )
    )

    if {"latitude", "longitude"}.issubset(output.columns):
        latitude = pd.to_numeric(output["latitude"], errors="coerce")
        longitude = pd.to_numeric(output["longitude"], errors="coerce")
        invalid_coordinates = int((~latitude.between(-90, 90) | ~longitude.between(-180, 180)).sum())
    else:
        invalid_coordinates = len(output)
    checks.append(
        _check(
            "Coordinate validity",
            5,
            "pass" if invalid_coordinates == 0 else "fail",
            f"Invalid coordinate pairs: {invalid_coordinates}.",
        )
    )

    if "station_osm_id" in output.columns and len(output):
        matched = output["station_osm_id"].notna() & output["station_osm_id"].astype(str).str.strip().ne("")
        match_rate = float(matched.mean())
    else:
        match_rate = 0.0
    match_status = "pass" if match_rate >= 0.95 else "warning" if match_rate >= 0.80 else "fail"
    checks.append(
        _check(
            "OpenStreetMap enrichment",
            10,
            match_status,
            f"Station match coverage: {match_rate:.1%}.",
        )
    )

    generated_at_valid = not pd.isna(pd.to_datetime(manifest.get("generated_at"), errors="coerce", utc=True))
    tool_present = bool(str(manifest.get("pipeline_tool", "")).strip())
    run_id_present = bool(str(manifest.get("run_id", "")).strip())
    run_metadata_complete = generated_at_valid and tool_present and run_id_present
    checks.append(
        _check(
            "Run metadata completeness",
            10,
            "pass" if run_metadata_complete else "fail",
            "Run identifier, pipeline tool and generation timestamp are present and valid."
            if run_metadata_complete
            else "Run identifier, tool or valid generation timestamp is missing.",
        )
    )

    metadata = {
        "student_or_team": manifest.get("student_or_team"),
        "run_id": manifest.get("run_id"),
        "pipeline_tool": manifest.get("pipeline_tool"),
        "output_columns": list(output.columns),
    }
    return _finish(checks, rows=len(output), metadata=metadata)


def _finish(checks: list[Check], rows: int, metadata: dict[str, Any]) -> dict[str, Any]:
    score = sum(check.points for check in checks)
    maximum = sum(check.maximum for check in checks)
    return {
        "score": score,
        "maximum": maximum,
        "rows": rows,
        "checks_passed": sum(check.status == "pass" for check in checks),
        "checks_total": len(checks),
        "checks": [asdict(check) for check in checks],
        "metadata": metadata,
    }
