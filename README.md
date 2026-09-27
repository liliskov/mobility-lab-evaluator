# Mobility Pipeline Lab Evaluator

Working prototype for a three-session Big Data Technology lab built around Belgian railway data and OpenStreetMap.

## What this repository contains

- `app.py`: Streamlit upload and feedback interface.
- `evaluator.py`: deterministic ZIP validation and formative feedback.
- `reference_pipeline.py`: small reference implementation that ingests schedule, real-time and OSM fixtures.
- `self_test.py`: builds the reference submission and runs it through exactly the same evaluator used by Streamlit.
- `sample_inputs/`: small GTFS-compatible and OSM-compatible fixtures for development.

The evaluator never executes uploaded code. It inspects only three declared output artifacts:

```text
submission.zip
├── output.csv
├── manifest.json
└── quality_report.json
```

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## Build and validate the reference submission

```bash
python self_test.py
```

The command must finish with `TOTAL: 100/100`. It also creates `reference_submission.zip`, which can be uploaded manually through the Streamlit interface.

## Build a submission from live Belgian rail and OpenStreetMap data

```bash
python real_pipeline.py
```

The live pipeline queries the iRail Liveboard and Vehicle APIs, selects a real
NMBS/SNCB train, retrieves its stop sequence and current delays, and enriches
the stations with OpenStreetMap objects through Nominatim, with Photon as an
OpenStreetMap-backed fallback for smaller railway halts. It preserves the raw
responses locally under `real_submission/raw/` and creates
`real_submission.zip` for the evaluator.

OpenStreetMap results are cached locally and Nominatim requests are deliberately
limited to at most one per second in accordance with its public usage policy.
Run it again later to produce a new package from the then-current operational
data.

## Current status

This is an executable proof of concept. The source fixtures and output contract are intentionally small and provisional. Before student use, they must be replaced by a frozen subset of the selected NMBS/SNCB, Infrabel and OpenStreetMap sources, and the final rubric must be agreed with the course lecturer.

The evaluator validates declared output artifacts and selected data invariants. It does not execute student code or independently assess architecture, scalability, implementation quality, source authenticity, replay-based idempotency or full reproducibility.

## Proposed real source strategy

1. NMBS/SNCB scheduled GTFS for the timetable baseline.
2. NMBS/SNCB GTFS-Realtime for train updates.
3. A frozen OpenStreetMap railway-station extract for reproducibility.
4. Optional Infrabel historical punctuality data for a predictive extension.

Public APIs should not be called repeatedly by every student during grading. A dated source snapshot should accompany the assignment, while live ingestion remains an optional exploration task.
