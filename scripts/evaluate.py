"""Run the grounded Q&A system against structured reliability cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.archive import ArchiveRepository  # noqa: E402
from src.qa import GroundedAnswerEngine  # noqa: E402


def evaluate() -> int:
    repository = ArchiveRepository.from_json(ROOT / "data" / "archive.json")
    engine = GroundedAnswerEngine(repository)
    with (ROOT / "data" / "evaluation_cases.json").open(encoding="utf-8") as cases_file:
        cases = json.load(cases_file)

    passed = 0
    print("THREADLINE RELIABILITY EVALUATION")
    print("=" * 38)
    for case in cases:
        answer = engine.answer(
            case["question"],
            universe_id=case["universe_id"],
            include_interpretations=case["include_interpretations"],
        )
        checks = [
            answer.status == case["expected_status"],
            all(fragment.casefold() in answer.text.casefold() for fragment in case["must_contain"]),
            bool(answer.sources) == case["requires_sources"],
            (answer.guardrail_note is not None) == case["requires_guardrail"],
        ]
        result = "PASS" if all(checks) else "FAIL"
        passed += int(all(checks))
        print(f"{result:4}  {case['id']}")
        print(f"      status={answer.status} confidence={answer.confidence:.2f} sources={len(answer.sources)}")
        if not all(checks):
            print(f"      checks={checks}")

    print("-" * 38)
    print(f"RESULT: {passed}/{len(cases)} cases passed ({passed / len(cases):.0%})")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(evaluate())

