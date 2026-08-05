import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    import anthropic
except ImportError:
    anthropic = None

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

_GREETING_PATTERNS = (
    r"^(?:hey|hello|hi|sup|yo|greetings|howdy|what'?s up)\b",
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
    """Answer questions with retrieved archive passages and optional Claude AI synthesis."""

    def __init__(
        self,
        repository: ArchiveRepository,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
    ):
        self.repository = repository
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model

    @staticmethod
    def _matches_any(patterns: tuple[str, ...], value: str) -> bool:
        return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)

    def _synthesize_with_claude(
        self,
        question: str,
        evidence: List[Dict],
        universe_name: str,
        private_state: bool,
        causal: bool,
    ) -> Optional[str]:
        if not self.api_key or not anthropic:
            return None

        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            formatted_passages = "\n".join(
                f"- [{item['claim_type']}] {item['title']}: {item['text']}" for item in evidence
            )
            system_prompt = (
                "You are Threadline AI, an expert music research assistant. "
                "Synthesize a clear, direct, and engaging response to the user's question using ONLY the "
                "reviewed evidence passages provided below. Respect these guardrails:\n"
                "- Do not infer private psychological states (depression, unstated feelings).\n"
                "- Do not state unconfirmed direct causation unless confirmed in the text.\n"
                "- Attribute context naturally (e.g. 'In documented accounts...', 'The artist publicly stated...')."
            )
            user_content = (
                f"Artist Universe: {universe_name}\n"
                f"Question: {question}\n\n"
                f"Reviewed Evidence Passages:\n{formatted_passages}"
            )
            response = client.messages.create(
                model=self.model,
                max_tokens=350,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text.strip()
        except Exception:
            return None

    def _conversational_response_with_claude(
        self, question: str, universe_name: str
    ) -> Optional[str]:
        if not self.api_key or not anthropic:
            return None
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            system_prompt = (
                "You are Threadline AI, a grounded music research assistant. "
                "The user is viewing the reviewed story archive. "
                "Respond in a friendly, helpful, conversational tone. Welcome them, "
                "briefly introduce Threadline's capabilities, and suggest asking about documented eras, "
                "releases, collaborators, or public statements."
            )
            response = client.messages.create(
                model=self.model,
                max_tokens=200,
                system=system_prompt,
                messages=[{"role": "user", "content": question}],
            )
            return response.content[0].text.strip()
        except Exception:
            return None

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
        is_greeting = self._matches_any(_GREETING_PATTERNS, clean_question) or len(clean_question) < 5

        universe_name = universe_id or "General Music Archive"
        if universe_id and hasattr(self.repository, "data") and isinstance(self.repository.data, dict):
            for u in self.repository.data.get("universes", []):
                if u.get("id") == universe_id:
                    universe_name = u.get("name", universe_id)
                    break

        results = self.repository.search(
            clean_question,
            universe_id=universe_id,
            include_interpretations=include_interpretations,
            limit=limit,
        )

        # Conversational fallback for greetings or short queries when Claude API key is available
        if (not results or results[0].confidence < 0.60) and is_greeting and self.api_key:
            claude_convo = self._conversational_response_with_claude(clean_question, universe_name)
            if claude_convo:
                return GroundedAnswer(
                    text=claude_convo,
                    status="answered",
                    confidence=1.0,
                    evidence=[],
                    sources=[],
                    guardrail_note="Powered by Claude AI · Grounded research guide",
                )

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

        # Try Claude AI synthesis if API key is active
        if self.api_key:
            claude_synth = self._synthesize_with_claude(
                clean_question,
                evidence,
                universe_name,
                private_state_request,
                causal_request,
            )
            if claude_synth:
                answer_text = claude_synth

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
        if self.api_key:
            guardrail_notes.append("Synthesized with Claude AI (grounded in reviewed archive).")

        confidence = round(sum(item["confidence"] for item in evidence) / len(evidence), 3)
        return GroundedAnswer(
            text=answer_text,
            status="answered",
            confidence=confidence,
            evidence=evidence,
            sources=self.repository.sources_for(source_ids),
            guardrail_note=" ".join(guardrail_notes) or None,
        )
