from __future__ import annotations

from evaluator import evaluate_submission
from reference_pipeline import build_reference_submission


def main() -> None:
    archive = build_reference_submission()
    result = evaluate_submission(archive.read_bytes())

    for check in result["checks"]:
        print(
            f"{check['status'].upper():7} "
            f"{check['points']:>2}/{check['maximum']:<2} "
            f"{check['name']}: {check['detail']}"
        )

    print(f"\nTOTAL: {result['score']}/{result['maximum']}")
    if result["score"] != result["maximum"]:
        raise SystemExit("Reference submission did not achieve the maximum score.")


if __name__ == "__main__":
    main()
