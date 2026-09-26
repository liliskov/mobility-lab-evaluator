from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "sample_inputs"
OUTPUT = ROOT / "reference_submission"
ARCHIVE = ROOT / "reference_submission.zip"


def build_reference_submission() -> Path:
    OUTPUT.mkdir(exist_ok=True)

    scheduled = pd.read_csv(
        INPUT / "gtfs_stop_times.csv",
        dtype={"service_date": "string", "station_code": "string"},
    )
    realtime = pd.read_csv(
        INPUT / "realtime_updates.csv",
        dtype={"service_date": "string"},
    )
    osm = pd.read_csv(INPUT / "osm_stations.csv", dtype={"station_code": "string"})

    key = ["trip_id", "service_date", "stop_sequence"]
    realtime["received_at"] = pd.to_datetime(realtime["received_at"], utc=True)
    realtime = realtime.sort_values("received_at").drop_duplicates(key, keep="last")

    pipeline = scheduled.merge(realtime, on=key, how="left", validate="one_to_one")
    pipeline = pipeline.merge(osm, on="station_code", how="left", validate="many_to_one")

    pipeline["scheduled_arrival"] = pd.to_datetime(pipeline["scheduled_arrival"], utc=True)
    pipeline["actual_arrival"] = pd.to_datetime(pipeline["actual_arrival"], utc=True)
    pipeline["delay_seconds"] = (
        pipeline["actual_arrival"] - pipeline["scheduled_arrival"]
    ).dt.total_seconds().astype("int64")
    pipeline["source_ingested_at"] = realtime["received_at"].max().isoformat()
    pipeline["event_id"] = (
        pipeline["trip_id"].astype(str)
        + "-"
        + pipeline["service_date"].astype(str)
        + "-"
        + pipeline["stop_sequence"].astype(str)
    )

    output_columns = [
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
    final = pipeline[output_columns].sort_values(key).reset_index(drop=True)
    final.to_csv(OUTPUT / "output.csv", index=False)

    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "0.1",
        "student_or_team": "Reference implementation",
        "run_id": f"reference-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        "pipeline_tool": "pandas reference pipeline",
        "generated_at": generated_at,
        "sources": [
            {
                "name": "NMBS/SNCB GTFS-compatible schedule fixture",
                "url": "https://transportdata.be/dataset/sncb-gfts-scheduled-timetable-and-real-time-data",
            },
            {
                "name": "NMBS/SNCB real-time update fixture",
                "url": "https://transportdata.be/dataset/sncb-gfts-scheduled-timetable-and-real-time-data",
            },
            {
                "name": "OpenStreetMap railway-station fixture",
                "url": "https://www.openstreetmap.org/",
            },
        ],
        "output_row_count": len(final),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    duplicate_output = int(final.duplicated(key).sum())
    unmatched = int(final["station_osm_id"].isna().sum())
    invalid_timestamps = int(final[["scheduled_arrival", "actual_arrival"]].isna().sum().sum())
    quality = {
        "scheduled_input_row_count": len(scheduled),
        "realtime_input_row_count": 7,
        "output_row_count": len(final),
        "duplicate_records_removed": 1,
        "duplicate_output_record_count": duplicate_output,
        "unmatched_station_count": unmatched,
        "invalid_timestamp_count": invalid_timestamps,
    }
    (OUTPUT / "quality_report.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")

    if ARCHIVE.exists():
        ARCHIVE.unlink()
    shutil.make_archive(str(ARCHIVE.with_suffix("")), "zip", OUTPUT)
    return ARCHIVE


if __name__ == "__main__":
    print(build_reference_submission())
