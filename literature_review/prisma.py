"""
prisma.py — PRISMA flow bookkeeping, done by CODE not by the LLM.

PRISMA (Preferred Reporting Items for Systematic reviews and Meta-Analyses) asks reviewers to
report how many records were identified, de-duplicated, screened, excluded and included.
We count these deterministically so the numbers in the review are always correct.

Change from the original kit: records dropped because of the `max_records` cap are reported
as "removed before screening (record cap)" instead of being counted as duplicates.

Adapted from the Codanics "Top five AI agents for research" kit (agent 02).
"""
from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field


class PrismaCounts(BaseModel):
    identified_per_source: dict[str, int] = Field(default_factory=dict)
    identified_total: int = 0
    duplicates_removed: int = 0
    removed_over_cap: int = 0
    screened: int = 0
    excluded: int = 0
    maybe: int = 0
    included: int = 0
    exclusion_reasons: dict[str, int] = Field(default_factory=dict)

    def flow_markdown(self) -> str:
        src = ", ".join(f"{k}: {v}" for k, v in self.identified_per_source.items()) or "n/a"
        reasons = "\n".join(f"  - {r}: {n}" for r, n in self.exclusion_reasons.items()) or "  - (none)"
        cap = (f"\n                 Removed before screening (record cap): {self.removed_over_cap}"
               if self.removed_over_cap else "")
        return f"""```
Identification   Records identified from databases: {self.identified_total}
                 ({src})
                              │
                 Duplicates removed: {self.duplicates_removed}{cap}
                              ▼
Screening        Records screened (title/abstract): {self.screened}
                              │
                 Records excluded: {self.excluded}   |  Uncertain / needs human check: {self.maybe}
                              ▼
Included         Studies included in the review: {self.included}
```
Exclusion reasons:
{reasons}
"""

    def flow_dot(self) -> str:
        """Graphviz DOT source for a PRISMA 2020-style flow diagram (rendered by the web app)."""
        src = "\\n".join(f"{k}: {v}" for k, v in self.identified_per_source.items()) or "n/a"
        removed = f"Duplicates removed: {self.duplicates_removed}"
        if self.removed_over_cap:
            removed += f"\\nRemoved over record cap: {self.removed_over_cap}"
        reasons = "\\n".join(f"{r}: {n}" for r, n in list(self.exclusion_reasons.items())[:6])
        excluded = f"Records excluded: {self.excluded}" + (f"\\n{reasons}" if reasons else "")
        return f"""digraph PRISMA {{
  newrank=true; rankdir=TB; nodesep=0.5; ranksep=0.4;
  node [shape=box, style="rounded,filled", fillcolor="#f4f7fb", color="#5b7db1", fontname="Helvetica",
        fontsize=15, width=3.6, margin="0.25,0.12"];
  id  [label="Records identified from databases\n(n = {self.identified_total})\n{src}"];
  rm  [label="Records removed before screening\n{removed}", fillcolor="#ffffff"];
  sc  [label="Records screened (title/abstract)\n(n = {self.screened})"];
  ex  [label="{excluded}", fillcolor="#ffffff"];
  inc [label="Studies included in review\n(n = {self.included})", fillcolor="#e9f6ec", color="#3a8a4f"];
  mb  [label="Uncertain — needs human check\n(n = {self.maybe})", fillcolor="#fff7e6", color="#c48a1a"];
  id -> sc -> inc;
  id -> rm [style=dashed]; sc -> ex [style=dashed]; sc -> mb [style=dashed];
  {{rank=same; id; rm}} {{rank=same; sc; ex}} {{rank=same; inc; mb}}
}}"""


def reason_key(reason: str) -> str:
    """Group exclusion reasons: drop a leading 'Excluded:' label and keep the first clause,
    so 'Excluded: not about breast imaging; animal study' counts as 'Not about breast imaging'."""
    text = re.sub(r"^\s*(excluded|exclude|exclusion)\s*[:\-–]\s*", "", reason.strip(), flags=re.I)
    text = re.split(r"[;.(]", text, maxsplit=1)[0].strip()[:60] or "No reason given"
    return text[0].upper() + text[1:]


def counts_from(identified_per_source: dict[str, int], n_after_dedupe: int, n_screened_pool: int,
                decisions: list) -> PrismaCounts:
    """Build PRISMA counts from stored totals (used after a human edits screening decisions).
    `decisions` is a list of objects/dicts with a decision in {include, exclude, maybe} and a reason."""
    def get(d, key):
        return d[key] if isinstance(d, dict) else getattr(d, key)

    total = sum(identified_per_source.values())
    dec = Counter(get(d, "decision") for d in decisions)
    reasons = Counter(reason_key(str(get(d, "reason"))) for d in decisions if get(d, "decision") == "exclude")
    return PrismaCounts(
        identified_per_source=dict(identified_per_source),
        identified_total=total,
        duplicates_removed=total - n_after_dedupe,
        removed_over_cap=n_after_dedupe - n_screened_pool,
        screened=len(decisions),
        excluded=dec.get("exclude", 0),
        maybe=dec.get("maybe", 0),
        included=dec.get("include", 0),
        exclusion_reasons=dict(reasons.most_common(10)),
    )


def build_counts(raw: list, deduped: list, decisions: list, n_after_dedupe: int | None = None) -> PrismaCounts:
    """`raw` = every retrieved record, `deduped` = the records sent to screening.
    Pass `n_after_dedupe` when `deduped` was truncated to a record cap."""
    per_source = Counter(getattr(p, "source", "unknown") for p in raw)
    n_dedup = n_after_dedupe if n_after_dedupe is not None else len(deduped)
    return counts_from(dict(per_source), n_dedup, len(deduped), decisions)
