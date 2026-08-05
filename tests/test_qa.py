from pathlib import Path

from src.archive import ArchiveRepository
from src.qa import GroundedAnswerEngine


ARCHIVE_PATH = Path(__file__).resolve().parents[1] / "data" / "archive.json"


def make_engine() -> GroundedAnswerEngine:
    return GroundedAnswerEngine(ArchiveRepository.from_json(ARCHIVE_PATH))


def test_grounded_answer_returns_sources_and_evidence():
    answer = make_engine().answer(
        "How did Odd Future use the internet?",
        universe_id="odd-future",
    )

    assert answer.status == "answered"
    assert answer.evidence
    assert answer.sources
    assert "Tumblr" in answer.text


def test_unknown_question_abstains():
    answer = make_engine().answer(
        "What did this artist eat for breakfast on an unknown Tuesday?",
        universe_id="tyler-the-creator",
    )

    assert answer.status == "insufficient-evidence"
    assert answer.evidence == []


def test_causal_question_receives_guardrail_note():
    answer = make_engine().answer(
        "Did Pharrell directly cause Tyler to make Flower Boy?",
        universe_id="tyler-the-creator",
    )

    assert answer.status == "answered"
    assert answer.guardrail_note
    assert "causation" in answer.guardrail_note.casefold()
    assert "does not contain a primary source" in answer.text


def test_empty_question_is_rejected():
    answer = make_engine().answer("   ", universe_id="odd-future")

    assert answer.status == "invalid-input"
    assert answer.confidence == 0.0

