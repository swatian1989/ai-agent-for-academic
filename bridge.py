"""
bridge.py — connects the two agents: Literature Review ─► Academic Writing.

The guide for the Writing Agent says it may cite "only user-provided notes and retrieved references
(optionally a references list from Agent 1/2)". This module turns a finished (or partly finished)
literature review into exactly that: a reference list with the same [id] tags the review used, and
the review text as background for the Introduction and Discussion.
"""
from __future__ import annotations

from pathlib import Path

from literature_review import workflow as lr
from literature_review.tools import Paper


def usable_reviews() -> list[Path]:
    """Reviews that have at least finished screening (so there is an included set)."""
    return [d for d in lr.list_reviews() if lr.status(d)["screening"]]


def review_label(out: Path) -> str:
    try:
        q = lr.load_settings(out)["question"]
    except Exception:
        q = out.name
    n = len(review_papers(out))
    return f"{q}  ({n} included papers)"


def review_papers(out: Path) -> list[Paper]:
    """The papers the review is built on: the evidence table if it exists, else the included set."""
    out = Path(out)
    if (out / "evidence.csv").exists():
        ids = {r.paper_id for r in lr.load_evidence(out)}
        return [p for p in lr.load_records(out) if p.id in ids]
    return lr.included_papers(out)


def format_reference(p: Paper) -> str:
    auth = ", ".join(p.authors[:6]) + (", et al." if len(p.authors) > 6 else "")
    parts = [f"[{p.id}]", f"{auth or 'Unknown authors'} ({p.year or 'n.d.'}).", f"{p.title}."]
    if p.venue:
        parts.append(f"{p.venue}.")
    if p.url:
        parts.append(p.url)
    return " ".join(parts)


def references_from_review(out: Path) -> str:
    return "\n".join(format_reference(p) for p in review_papers(out))


def background_from_review(out: Path) -> str:
    """The review draft without its generator footer ('' if the review has not been written yet)."""
    out = Path(out)
    if not (out / "review.md").exists():
        return ""
    text = lr.load_review(out)
    return text.rsplit("\n---\n", 1)[0].strip() if "\n---\n*Draft generated" in text else text.strip()
