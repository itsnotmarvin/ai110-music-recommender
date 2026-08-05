"""Grounded, extractive question answering over the reviewed archive."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .archive import ArchiveRepository, SearchResult


_PRIVATE_STATE_PATTERNS = (
    r"\bdiagnos(?:e|ed|is)\b",
    r"\bmental illness\b",
    r"\bpsychological state\b",
    r"\bsecretly (?:felt|thought|wanted)\b",
    r"\bwas (?:he|she|they) depressed\b",
)

_CAUSAL_PATTERNS = (
    r"\bcaused?\b",
    r"\bmade (?:him|her|them) (?:write|make|release)\b",
    r"\bdirectly led\b",
)


@dataclass(frozen=True)
class GroundedAnswer:
    """A response plus inspectable evidence and reliability metadata."""

    text: str
    status: str
    confidence: float
    evidence: List[Dict]
    sources: List[Dict]
    guardrail_note: Optional[str] = None


class GroundedAnswerEngine:
    """Answer questions only with retrieved and reviewed archive passages."""

    def __init__(self, repository: ArchiveRepository):
        self.repository = repository

    @staticmethod
    def _matches_any(patterns: tuple[str, ...], value: str) -> bool:
        return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)

    def answer(
        self,
        question: str,
        *,
        universe_id: Optional[str] = None,
        include_interpretations: bool = False,
        limit: int = 3,
    ) -> GroundedAnswer:
        clean_question = " ".join(question.split())
        if not clean_question:
            return GroundedAnswer(
                text="Ask a specific question about an artist, release, relationship, or era.",
                status="invalid-input",
                confidence=0.0,
                evidence=[],
                sources=[],
            )

        private_state_request = self._matches_any(_PRIVATE_STATE_PATTERNS, clean_question)
        causal_request = self._matches_any(_CAUSAL_PATTERNS, clean_question)
        results = self.repository.search(
            clean_question,
            universe_id=universe_id,
            include_interpretations=include_interpretations,
            limit=limit,
        )

        # A single entity-name match can produce a plausible-looking but unrelated
        # passage. Requiring 0.60 coverage-based confidence prevents that weak
        # match from becoming an answer.
        if not results or results[0].confidence < 0.60:
            return GroundedAnswer(
                text=(
                    "The reviewed archive does not contain enough evidence to answer that "
                    "reliably. Try asking about a documented era, release, collaborator, or "
                    "public statement."
                ),
                status="insufficient-evidence",
                confidence=results[0].confidence if results else 0.0,
                evidence=[],
                sources=[],
                guardrail_note=(
                    "Threadline abstains when retrieval confidence is too low."
                ),
            )

        evidence: List[Dict] = []
        source_ids: List[str] = []
        for result in results:
            document = result.document
            evidence.append(
                {
                    "title": document["title"],
                    "text": document["text"],
                    "claim_type": document["claim_type"],
                    "confidence": result.confidence,
                    "source_ids": document["source_ids"],
                    "matched_terms": list(result.matched_terms),
                }
            )
            for source_id in document["source_ids"]:
                if source_id not in source_ids:
                    source_ids.append(source_id)

        top = evidence[0]
        lead = "The reviewed archive indicates that"
        if top["claim_type"] == "artist-stated":
            lead = "In the artist's public account"
        elif top["claim_type"] == "reported":
            lead = "Contemporary reporting in the reviewed archive says that"
        elif top["claim_type"] == "critical-interpretation":
            lead = "A reviewed critic interprets the material this way:"

        answer_text = f"{lead} {top['text']}"
        if len(evidence) > 1:
            answer_text += f" Related context: {evidence[1]['text']}"

        guardrail_notes: List[str] = []
        if private_state_request:
            guardrail_notes.append(
                "Private psychological states cannot be inferred. The answer is limited "
                "to public statements and documented context."
            )
        if causal_request:
            guardrail_notes.append(
                "A sequence or influence does not prove direct causation unless an artist "
                "explicitly confirms it."
            )

        confidence = round(sum(item["confidence"] for item in evidence) / len(evidence), 3)
        return GroundedAnswer(
            text=answer_text,
            status="answered",
            confidence=confidence,
            evidence=evidence,
            sources=self.repository.sources_for(source_ids),
            guardrail_note=" ".join(guardrail_notes) or None,
        )
