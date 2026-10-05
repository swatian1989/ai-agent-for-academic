"""
agents.py — the four sub-agents of the Literature Review Agent (PRISMA pipeline).

    1. SearchAgent      : review protocol (PICO-style question, criteria, database queries)
    2. ScreeningAgent   : include / exclude / maybe + reason, in batches (structured)
    3. ExtractionAgent  : evidence table rows (structured)
    4. WritingAgent     : the literature review draft (free text, cites only included IDs)

Adapted from the Codanics "Top five AI agents for research" kit (agent 02).
"""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, Field

from llm import ask, ask_structured

from .prisma import PrismaCounts
from .tools import Paper

FOOTER = ("*Draft generated with the AI Literature Review Agent (AI Agent for Academic). "
          "Check every citation, number and claim against the original papers before use.*")

CITE_RULE = ("CITATION RULE: cite ONLY papers given in the input using their exact [id] tags. "
             "Never invent papers, numbers or findings.")


# ================================================================ 1. Search / protocol
class Protocol(BaseModel):
    review_title: str
    research_question: str
    pico_or_scope: str = Field(description="Population/Problem, Intervention/Method, Comparison, Outcome (or scope)")
    inclusion_criteria: list[str]
    exclusion_criteria: list[str]
    queries: list[str] = Field(description="3-6 search strings for the databases")
    year_from: int | None = None


class SearchAgent:
    SYSTEM = ("You are a systematic-review methodologist (PRISMA 2020). Write precise protocols with "
              "operational inclusion/exclusion criteria and high-recall search strings.")

    def run(self, question: str) -> Protocol:
        return ask_structured(self.SYSTEM, f"Review question: {question}", Protocol, effort="low")


# ===================================================================== 2. Screening
class Decision(BaseModel):
    paper_id: str
    decision: Literal["include", "exclude", "maybe"]
    reason: str = Field(description="Short reason, e.g. 'Excluded: not about plant disease' or 'Included: CNN on leaf images'")


class ScreeningBatch(BaseModel):
    decisions: list[Decision]


class ScreeningAgent:
    SYSTEM = ("You are a careful title/abstract screener for a systematic review. Apply the protocol "
              "criteria literally. Use 'maybe' when the abstract is insufficient. Return one decision per paper.")

    def run(self, protocol: Protocol, papers: list[Paper], batch_size: int = 10, log=print) -> list[Decision]:
        decisions: list[Decision] = []
        for i in range(0, len(papers), batch_size):
            batch = papers[i:i + batch_size]
            corpus = "\n".join(p.short(1200) for p in batch)
            res = ask_structured(
                self.SYSTEM,
                f"Protocol:\n{protocol.model_dump_json(indent=1)}\n\nPapers to screen:\n{corpus}\n\n"
                f"Return exactly {len(batch)} decisions with the given paper ids.",
                ScreeningBatch, effort="low", task="bulk")
            got = {d.paper_id: d for d in res.decisions}
            for p in batch:  # guarantee one decision per paper even if the model skipped one
                decisions.append(got.get(p.id, Decision(paper_id=p.id, decision="maybe",
                                                        reason="No decision returned; needs human check")))
            log(f"screened {min(i + batch_size, len(papers))}/{len(papers)}")
        return decisions


# ==================================================================== 3. Extraction
class EvidenceRow(BaseModel):
    paper_id: str
    study: str = Field(description="First author + year, e.g. 'Smith 2025'")
    objective: str
    dataset_or_sample: str
    method: str
    key_result: str = Field(description="Main quantitative/qualitative result, e.g. '94% accuracy'")
    limitations: str
    theme: str = Field(description="Short theme label for grouping, e.g. 'CNN on leaf images'")


class EvidenceTable(BaseModel):
    rows: list[EvidenceRow]


class ExtractionAgent:
    SYSTEM = ("You extract structured evidence from abstracts for a systematic review. If a field is not "
              "reported, write 'not reported'. " + CITE_RULE)

    def run(self, protocol: Protocol, papers: list[Paper], batch_size: int = 8, log=print) -> list[EvidenceRow]:
        rows: list[EvidenceRow] = []
        for i in range(0, len(papers), batch_size):
            batch = papers[i:i + batch_size]
            corpus = "\n".join(p.short(1500) for p in batch)
            res = ask_structured(
                self.SYSTEM,
                f"Review question: {protocol.research_question}\n\nPapers:\n{corpus}\n\n"
                f"Return one row per paper ({len(batch)} rows).",
                EvidenceTable, effort="medium", task="bulk")
            got = {r.paper_id: r for r in res.rows}
            for p in batch:  # every included paper gets exactly one row, and only real ids are kept
                rows.append(got.get(p.id) or EvidenceRow(
                    paper_id=p.id, study=_study_label(p), objective="not extracted — needs human check",
                    dataset_or_sample="not extracted", method="not extracted", key_result="not extracted",
                    limitations="not extracted", theme="unclassified"))
            log(f"extracted {min(i + batch_size, len(papers))}/{len(papers)}")
        return rows


def _study_label(p: Paper) -> str:
    first = (p.authors[0].split()[-1] if p.authors else "Unknown")
    return f"{first} {p.year or 'n.d.'}"


# ======================================================================= 4. Writing
class WritingAgent:
    SYSTEM = ("You are an academic writer producing a systematic literature review in Markdown. "
              + CITE_RULE + " Structure: Title; Abstract; 1 Introduction; 2 Methods (PRISMA: databases, "
              "queries, criteria, screening, extraction); 3 Results (3.1 Study characteristics, "
              "3.2-3.x Thematic synthesis with an evidence table); 4 Research Gaps; 5 Discussion; "
              "6 Conclusion; References (only cited ids, one per line with title). "
              "Be specific and quantitative; do not pad.")

    def run(self, protocol: Protocol, prisma: PrismaCounts, rows: list[EvidenceRow],
            included: list[Paper], echo: bool = False,
            on_text: Callable[[str], None] | None = None) -> str:
        table = "\n".join(r.model_dump_json() for r in rows)
        refs = "\n".join(f"[{p.id}] {p.title} ({p.year}) {p.venue}" for p in included)
        text = ask(
            self.SYSTEM,
            f"Protocol:\n{protocol.model_dump_json(indent=1)}\n\nPRISMA counts (use these numbers verbatim):\n"
            f"{prisma.model_dump_json(indent=1)}\n\nEvidence table rows:\n{table}\n\n"
            f"Included papers (for citation):\n{refs}\n\nWrite the full review.",
            max_tokens=64000, effort="high", echo=echo, on_text=on_text)
        return text + f"\n\n---\n{FOOTER}\n"
