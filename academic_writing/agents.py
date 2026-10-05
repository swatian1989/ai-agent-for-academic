"""
agents.py — the four sub-agents of the Academic Writing & Publication Agent.

    ManuscriptAgent        : notes/results ─► IMRaD manuscript (Markdown)
    JournalMatchingAgent   : manuscript + catalogue ─► ranked journals (structured)
    ReviewerSimulationAgent: manuscript ─► N reviewers with personas (structured)
    RevisionAgent          : manuscript + reviews ─► response letter + revised manuscript

Adapted from the Codanics "Top five AI agents for research" kit (agent 04).
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, Field

from llm import ask, ask_structured

from .journals import catalogue_text

FOOTER = ("*Draft generated with the AI Academic Writing & Publication Agent (AI Agent for Academic). "
          "Review every statement before sending.*")

NO_FABRICATION = ("STRICT RULE: use only facts, numbers and references present in the input. If something is "
                  "missing, write '[TO BE ADDED BY AUTHORS]' instead of inventing it.")

AI_STATEMENT = ("\n\n## Declaration of AI assistance\n"
                "An AI writing assistant (AI Academic Writing & Publication Agent) was used to draft and structure "
                "this manuscript from the authors' notes and results. All content was reviewed, verified and "
                "approved by the authors, who take full responsibility for the work.\n")

OnText = Callable[[str], None] | None


# ------------------------------------------------------------------- 1. Manuscript
class ManuscriptAgent:
    SYSTEM = ("You are an experienced academic writer and editor. Write a complete manuscript in Markdown "
              "with: Title; Authors placeholder; Abstract (250 words, structured); Keywords; 1 Introduction "
              "(with the gap and objectives); 2 Materials and Methods; 3 Results; 4 Discussion; 5 Conclusion; "
              "Acknowledgements placeholder; References (only those given). Clear, concise academic English "
              "suitable for non-native authors. " + NO_FABRICATION)

    def run(self, notes: str, field: str, references: str = "", background: str = "",
            echo: bool = False, on_text: OnText = None) -> str:
        bg = (f"\n\nBackground literature synthesis from the authors' own systematic review (use it for the "
              f"Introduction and Discussion; cite papers only with the [id] tags listed under References "
              f"available):\n{background}") if background else ""
        text = ask(self.SYSTEM,
                   f"Field: {field}\n\nAuthor notes and results:\n{notes}{bg}\n\nReferences available:\n"
                   f"{references or '(none provided)'}\n\nWrite the manuscript.",
                   max_tokens=64000, effort="high", echo=echo, on_text=on_text)
        return text + AI_STATEMENT


# ------------------------------------------------------------- 2. Journal matching
class JournalMatch(BaseModel):
    journal: str
    scope_fit: int = Field(ge=1, le=10)
    impact_band: str
    open_access: str
    estimated_apc_usd: int | None
    acceptance_probability: str = Field(description="low | medium | high, with the main reason")
    reason: str
    tips_for_this_journal: str


class JournalRanking(BaseModel):
    manuscript_summary: str
    matches: list[JournalMatch] = Field(description="Top 5, best first")
    avoid: list[str] = Field(description="Journals from the catalogue that are a poor fit, with a reason")


class JournalMatchingAgent:
    SYSTEM = ("You are a journal-selection consultant. Score journals from the provided catalogue ONLY "
              "(never invent journals). Balance scope fit, impact, cost, speed and realistic acceptance odds. "
              "Where a journal has `live_openalex` data, prefer its APC and open-access values; where the APC "
              "is unknown (null), set estimated_apc_usd to null rather than guessing.")

    def run(self, manuscript: str) -> JournalRanking:
        return ask_structured(self.SYSTEM,
                              f"Journal catalogue:\n{catalogue_text()}\n\nManuscript:\n{manuscript[:20000]}",
                              JournalRanking, effort="medium")


# ----------------------------------------------------------- 3. Reviewer simulation
class ReviewComment(BaseModel):
    number: int
    section: str
    comment: str
    severity: str = Field(description="minor | major | critical")


class Review(BaseModel):
    reviewer: str = Field(description="e.g. 'Reviewer 1 (methodologist)'")
    summary: str
    comments: list[ReviewComment]
    recommendation: str = Field(description="accept | minor revision | major revision | reject")


class ReviewSet(BaseModel):
    reviews: list[Review]


PERSONAS = [
    "Reviewer 1 — a strict methodologist who focuses on validation, controls, sample size and reproducibility",
    "Reviewer 2 — a domain expert who checks novelty, dataset selection, related work and interpretation",
    "Reviewer 3 — a statistician/data scientist who checks tests, leakage, metrics and figures",
]


class ReviewerSimulationAgent:
    SYSTEM = ("You simulate peer review for a scientific manuscript. Each reviewer has a distinct persona and "
              "must give specific, numbered, actionable comments (quote the problematic sentence when possible). "
              "Be tough but fair.")

    def run(self, manuscript: str, n_reviewers: int = 3) -> ReviewSet:
        personas = "\n".join(PERSONAS[:n_reviewers])
        return ask_structured(self.SYSTEM,
                              f"Reviewer personas:\n{personas}\n\nManuscript:\n{manuscript[:30000]}\n\n"
                              f"Produce {n_reviewers} reviews.",
                              ReviewSet, max_tokens=64000, effort="high")


# ----------------------------------------------------------------- 4. Revision
class RevisionAgent:
    SYSTEM_LETTER = ("You write point-by-point response letters to reviewers. For EVERY comment: quote it, "
                     "respond politely and concretely, and state exactly what was changed and where "
                     "(section/paragraph). If a change is impossible, explain why respectfully. Markdown.")
    SYSTEM_REVISE = ("You revise scientific manuscripts to address reviewer comments. Return the FULL revised "
                     "manuscript in Markdown. Mark changed passages by wrapping them in **bold**. "
                     + NO_FABRICATION)

    def letter(self, manuscript: str, reviews: ReviewSet, echo: bool = False, on_text: OnText = None) -> str:
        text = ask(self.SYSTEM_LETTER,
                   f"Reviews:\n{reviews.model_dump_json(indent=1)}\n\nManuscript:\n{manuscript[:30000]}",
                   effort="high", echo=echo, on_text=on_text)
        return text + f"\n\n---\n{FOOTER}\n"

    def revise(self, manuscript: str, reviews: ReviewSet, echo: bool = False, on_text: OnText = None) -> str:
        return ask(self.SYSTEM_REVISE,
                   f"Reviews:\n{reviews.model_dump_json(indent=1)}\n\nOriginal manuscript:\n{manuscript}",
                   max_tokens=64000, effort="high", echo=echo, on_text=on_text)
