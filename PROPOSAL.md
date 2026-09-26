# Proposed Big Data Technology Lab Series

## Theme

Build an end-to-end Belgian railway mobility pipeline using self-selected technologies.

## Learning objective

Students ingest scheduled and real-time railway data, preserve raw records, normalise and reconcile events, enrich stations using OpenStreetMap, publish a stable analytical dataset, and report data-quality and reproducibility metadata.

## Three-session progression

1. **Ingestion and raw layer** — obtain the supplied GTFS/GTFS-Realtime and OSM sources, preserve source metadata, and create a repeatable raw ingestion step.
2. **Integration and resilience** — normalise timestamps and identifiers, deduplicate updates, handle missing or late records, and enrich stopping points with OpenStreetMap station data.
3. **Publication and evaluation** — publish the agreed output contract, produce a quality report, validate idempotency and reproducibility, and optionally create a delay or occupancy prediction.

## Technology policy

Students select their own suitable technology. The assessment targets observable pipeline behaviour and the shared output contract rather than a particular language or framework.

## Automated formative evaluation

Students upload a ZIP containing the analytical output, a run manifest and a quality report. The evaluator returns immediate deterministic feedback on:

- package and schema correctness;
- lineage and reproducibility metadata;
- row-count reconciliation;
- duplicate handling and idempotency;
- timestamp and coordinate validity;
- OpenStreetMap match coverage;
- declared quality metrics.

The evaluator does not execute student code and is initially formative rather than an official grading authority.

## Open question

If a sufficiently complete occupancy dataset from the Ypto/iRail context is available, occupancy prediction can be offered as an extension. Otherwise, delay prediction using Infrabel historical punctuality data is the safer option.
