from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


IRAIL_BASE_URL = "https://api.irail.be"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_SEARCH_URL = "https://photon.komoot.io/api/"
USER_AGENT = (
    "UGent-Mobility-Lab-Evaluator/0.1 "
    "(+https://github.com/liliskov/mobility-lab-evaluator)"
)
BELGIUM_TIMEZONE = ZoneInfo("Europe/Brussels")

OUTPUT_COLUMNS = [
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


def fetch_json(url: str, parameters: dict[str, Any], attempts: int = 3) -> Any:
    query = urllib.parse.urlencode(parameters)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"Request failed after {attempts} attempts: {url}") from exc
            time.sleep(2**attempt)

    raise RuntimeError(f"Request unexpectedly failed: {url}")


def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def load_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {}
    with cache_path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def osm_station_match(
    station_name: str,
    latitude: float,
    longitude: float,
    cache: dict[str, Any],
) -> dict[str, Any] | None:
    cache_key = f"{station_name}|{latitude:.6f}|{longitude:.6f}"
    if cache_key in cache and cache[cache_key] is not None:
        return cache[cache_key]

    name_variants = [station_name]
    name_variants.extend(
        part.strip() for part in station_name.split("/") if part.strip() != station_name
    )
    queries = []
    for name_variant in dict.fromkeys(name_variants):
        queries.extend(
            [
                f"{name_variant} railway station Belgium",
                f"Station {name_variant} Belgium",
            ]
        )
    candidates: list[dict[str, Any]] = []

    for query in queries:
        # The public Nominatim service permits at most one request per second.
        time.sleep(1.05)
        try:
            response = fetch_json(
                NOMINATIM_SEARCH_URL,
                {
                    "q": query,
                    "format": "jsonv2",
                    "countrycodes": "be",
                    "limit": 5,
                    "addressdetails": 0,
                },
            )
        except RuntimeError as exc:
            print(f"OSM lookup temporarily unavailable for {station_name}: {exc}")
            break
        if isinstance(response, list):
            candidates.extend(response)
        if candidates:
            break

    ranked: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        try:
            candidate_latitude = float(candidate["lat"])
            candidate_longitude = float(candidate["lon"])
        except (KeyError, TypeError, ValueError):
            continue

        category = str(candidate.get("category", "")).lower()
        object_type = str(candidate.get("type", "")).lower()
        if category not in {"railway", "public_transport"} and object_type not in {
            "station",
            "train_station",
            "halt",
            "stop",
        }:
            continue

        distance = haversine_metres(
            latitude,
            longitude,
            candidate_latitude,
            candidate_longitude,
        )
        ranked.append((distance, candidate))

    ranked.sort(key=lambda item: item[0])
    if not ranked or ranked[0][0] > 2_000:
        # Nominatim sometimes omits small Belgian railway halts from text
        # searches. Photon uses the same OpenStreetMap data but indexes these
        # objects differently, so use it as a coordinate-biased fallback.
        try:
            photon_response = fetch_json(
                PHOTON_SEARCH_URL,
                {
                    "q": station_name,
                    "lat": latitude,
                    "lon": longitude,
                    "limit": 10,
                    "lang": "en",
                },
            )
        except RuntimeError as exc:
            print(f"OSM fallback lookup unavailable for {station_name}: {exc}")
            photon_response = {}

        photon_ranked: list[tuple[float, dict[str, Any]]] = []
        osm_type_names = {"N": "node", "W": "way", "R": "relation"}
        for feature in photon_response.get("features", []):
            properties = feature.get("properties", {})
            coordinates = feature.get("geometry", {}).get("coordinates", [])
            if len(coordinates) < 2:
                continue
            osm_key = str(properties.get("osm_key", "")).lower()
            osm_value = str(properties.get("osm_value", "")).lower()
            if osm_key not in {"railway", "public_transport"} or osm_value not in {
                "station",
                "halt",
                "stop",
                "stop_position",
            }:
                continue
            candidate_longitude, candidate_latitude = map(float, coordinates[:2])
            distance = haversine_metres(
                latitude,
                longitude,
                candidate_latitude,
                candidate_longitude,
            )
            photon_ranked.append((distance, feature))

        photon_ranked.sort(key=lambda item: item[0])
        if not photon_ranked or photon_ranked[0][0] > 2_000:
            cache[cache_key] = None
            return None

        distance, feature = photon_ranked[0]
        properties = feature["properties"]
        match = {
            "osm_type": osm_type_names.get(
                str(properties.get("osm_type", "")).upper(),
                str(properties.get("osm_type", "")).lower(),
            ),
            "osm_id": properties["osm_id"],
            "display_name": properties.get("name"),
            "distance_metres": round(distance, 1),
            "lookup_service": "Photon",
        }
        cache[cache_key] = match
        return match

    distance, candidate = ranked[0]
    match = {
        "osm_type": candidate["osm_type"],
        "osm_id": candidate["osm_id"],
        "display_name": candidate.get("display_name"),
        "distance_metres": round(distance, 1),
        "lookup_service": "Nominatim",
    }
    cache[cache_key] = match
    return match


def select_vehicle(liveboard: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    departures = liveboard.get("departures", {}).get("departure", [])
    if isinstance(departures, dict):
        departures = [departures]

    candidates = [
        departure
        for departure in departures
        if departure.get("vehicle")
        and not str(departure["vehicle"]).startswith("BE.NMBS.BUS")
        and str(departure.get("canceled", "0")) != "1"
    ]
    if not candidates:
        raise RuntimeError("The liveboard did not contain a usable non-bus train departure.")

    for departure in candidates[:8]:
        vehicle_id = str(departure["vehicle"])
        departure_epoch = int(departure["time"])
        service_date = datetime.fromtimestamp(
            departure_epoch, tz=timezone.utc
        ).astimezone(BELGIUM_TIMEZONE)
        vehicle = fetch_json(
            f"{IRAIL_BASE_URL}/vehicle/",
            {
                "id": vehicle_id,
                "date": service_date.strftime("%d%m%y"),
                "format": "json",
                "lang": "en",
                "alerts": "false",
            },
        )
        stops = vehicle.get("stops", {}).get("stop", [])
        if isinstance(stops, list) and len(stops) >= 2:
            return departure, vehicle

    raise RuntimeError("None of the first live train departures returned a usable stop sequence.")


def timestamp_from_epoch(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def build_rows(
    vehicle: dict[str, Any],
    ingested_at: datetime,
    osm_cache: dict[str, Any],
    cache_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_stops = vehicle["stops"]["stop"]
    trip_id = str(vehicle.get("vehicle") or vehicle.get("vehicleinfo", {}).get("name"))
    rows: list[dict[str, Any]] = []
    osm_matches: list[dict[str, Any]] = []

    for sequence, stop in enumerate(raw_stops, start=1):
        station = stop.get("stationinfo", {})
        station_name = str(station.get("standardname") or station.get("name") or stop["station"])
        station_identifier = str(station.get("id") or station.get("@id") or "")
        station_code = station_identifier.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        latitude = float(station["locationY"])
        longitude = float(station["locationX"])

        scheduled_epoch = (
            stop.get("scheduledArrivalTime")
            or stop.get("scheduledDepartureTime")
            or stop.get("time")
        )
        if scheduled_epoch is None:
            raise RuntimeError(f"Stop {station_name} has no scheduled timestamp.")

        delay_seconds = int(stop.get("arrivalDelay") or stop.get("delay") or 0)
        scheduled_arrival = timestamp_from_epoch(scheduled_epoch)
        actual_arrival = scheduled_arrival + timedelta(seconds=delay_seconds)
        service_date = scheduled_arrival.astimezone(BELGIUM_TIMEZONE).strftime("%Y%m%d")

        osm_match = osm_station_match(
            station_name,
            latitude,
            longitude,
            osm_cache,
        )
        save_json(cache_path, osm_cache)
        print(
            f"OSM enrichment {sequence}/{len(raw_stops)}: {station_name} -> "
            f"{osm_match['osm_type']}/{osm_match['osm_id']}"
            if osm_match
            else f"OSM enrichment {sequence}/{len(raw_stops)}: {station_name} -> unmatched"
        )
        station_osm_id = (
            f"{osm_match['osm_type']}/{osm_match['osm_id']}" if osm_match else ""
        )
        osm_matches.append(
            {
                "station_code": station_code,
                "station_name": station_name,
                "station_osm_id": station_osm_id,
                "match": osm_match,
            }
        )

        rows.append(
            {
                "event_id": f"{trip_id}-{service_date}-{sequence}",
                "trip_id": trip_id,
                "stop_sequence": sequence,
                "service_date": service_date,
                "station_code": station_code,
                "station_osm_id": station_osm_id,
                "station_name": station_name,
                "scheduled_arrival": scheduled_arrival.isoformat(),
                "actual_arrival": actual_arrival.isoformat(),
                "delay_seconds": delay_seconds,
                "latitude": latitude,
                "longitude": longitude,
                "source_ingested_at": ingested_at.isoformat(),
            }
        )

    return rows, osm_matches


def build_real_submission(station: str, output_directory: Path) -> Path:
    ingested_at = datetime.now(timezone.utc)
    output_directory.mkdir(parents=True, exist_ok=True)
    raw_directory = output_directory / "raw"
    cache_path = Path(".cache") / "osm_station_matches.json"
    osm_cache = load_cache(cache_path)

    liveboard = fetch_json(
        f"{IRAIL_BASE_URL}/liveboard/",
        {
            "station": station,
            "arrdep": "departure",
            "format": "json",
            "lang": "en",
            "alerts": "false",
        },
    )
    departure, vehicle = select_vehicle(liveboard)
    rows, osm_matches = build_rows(vehicle, ingested_at, osm_cache, cache_path)
    save_json(cache_path, osm_cache)

    save_json(raw_directory / "liveboard.json", liveboard)
    save_json(raw_directory / "vehicle.json", vehicle)
    save_json(raw_directory / "osm_matches.json", osm_matches)

    output = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    before_deduplication = len(output)
    output = output.drop_duplicates(
        subset=["trip_id", "service_date", "stop_sequence"], keep="last"
    ).reset_index(drop=True)
    duplicates_removed = before_deduplication - len(output)

    invalid_timestamp_count = 0
    for column in ["scheduled_arrival", "actual_arrival", "source_ingested_at"]:
        invalid_timestamp_count += int(
            pd.to_datetime(output[column], errors="coerce", utc=True).isna().sum()
        )

    unmatched_station_count = int(output["station_osm_id"].eq("").sum())
    duplicate_output_record_count = int(
        output.duplicated(["trip_id", "service_date", "stop_sequence"]).sum()
    )

    vehicle_id = str(vehicle.get("vehicle"))
    run_id = f"live-{ingested_at.strftime('%Y%m%dT%H%M%SZ')}"
    manifest = {
        "schema_version": "0.1",
        "student_or_team": "Live reference pipeline",
        "run_id": run_id,
        "pipeline_tool": "Python and pandas live-data pipeline",
        "generated_at": ingested_at.isoformat(),
        "sources": [
            {
                "name": "NMBS/SNCB live operational data via the iRail Liveboard API",
                "url": f"{IRAIL_BASE_URL}/liveboard/",
                "station": station,
            },
            {
                "name": "NMBS/SNCB train stop and delay data via the iRail Vehicle API",
                "url": f"{IRAIL_BASE_URL}/vehicle/",
                "vehicle": vehicle_id,
            },
            {
                "name": "OpenStreetMap station objects via Nominatim",
                "url": NOMINATIM_SEARCH_URL,
                "attribution": "© OpenStreetMap contributors, ODbL",
            },
            {
                "name": "OpenStreetMap station-object fallback via Photon",
                "url": PHOTON_SEARCH_URL,
                "attribution": "© OpenStreetMap contributors, ODbL",
            },
        ],
        "selected_departure": {
            "vehicle": departure.get("vehicle"),
            "destination": departure.get("station"),
            "scheduled_epoch": departure.get("time"),
        },
        "output_row_count": len(output),
    }
    quality_report = {
        "scheduled_input_row_count": len(rows),
        "realtime_input_row_count": len(rows),
        "output_row_count": len(output),
        "duplicate_records_removed": duplicates_removed,
        "duplicate_output_record_count": duplicate_output_record_count,
        "unmatched_station_count": unmatched_station_count,
        "invalid_timestamp_count": invalid_timestamp_count,
    }

    output.to_csv(output_directory / "output.csv", index=False)
    save_json(output_directory / "manifest.json", manifest)
    save_json(output_directory / "quality_report.json", quality_report)

    archive_path = output_directory.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in ["output.csv", "manifest.json", "quality_report.json"]:
            archive.write(output_directory / filename, arcname=filename)

    print(f"Selected live train: {vehicle_id} to {departure.get('station')}")
    print(f"Stops written: {len(output)}")
    print(f"OpenStreetMap matches: {len(output) - unmatched_station_count}/{len(output)}")
    print(f"Submission package: {archive_path}")
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an evaluator submission from live Belgian railway and OSM data."
    )
    parser.add_argument("--station", default="Gent-Sint-Pieters")
    parser.add_argument("--output", default="real_submission")
    arguments = parser.parse_args()

    build_real_submission(arguments.station, Path(arguments.output))


if __name__ == "__main__":
    main()
