"""
workflow.py — the PRISMA pipeline as resumable stages, each saved to disk (the audit trail).

    question ─► protocol ─► search (4 databases) ─► screen ─► PRISMA counts ─► extract ─► review.md

Both the command-line tool (main.py) and the web app (app.py) call these functions, so a review
started in one can be continued in the other. Every stage reads its inputs from, and writes its
outputs to, one folder:

    settings.json    question + search settings
    protocol.json    review protocol (editable)
    identified.json  records identified per database, after de-duplication, sent to screening
    records.json     the records sent to screening
    screening.csv    one decision per record: ai_decision (the model) and decision (final, editable)
    prisma.json      PRISMA counts, always recomputed by code from screening.csv
    evidence.csv     evidence table for included studies (editable)
    review.md        the review draft
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable

from slugify import slugify

from .agents import (EvidenceRow, ExtractionAgent, Protocol, ScreeningAgent, SearchAgent,
                     WritingAgent)
from .prisma import PrismaCounts, counts_from
from .tools import OFFLINE_SAMPLE, SOURCES, Paper, dedupe, search_all

APP_DIR = Path(__file__).resolve().parent.parent
REVIEWS_DIR = APP_DIR / "Outputs" / "Literature reviews"
ALL_SOURCES = list(SOURCES)
SCREENING_FIELDS = ["paper_id", "title", "year", "ai_decision", "decision", "reason"]
EVIDENCE_FIELDS = list(EvidenceRow.model_fields)

Log = Callable[[str], None]


# ----------------------------------------------------------------------------- files
def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------- folders
def new_review_dir(question: str, base: Path = REVIEWS_DIR) -> Path:
    """A fresh folder named after the question; never overwrites an earlier review."""
    stem = slugify(question)[:60] or "review"
    out, n = base / stem, 2
    while out.exists() and any(out.iterdir()):
        out, n = base / f"{stem}-{n}", n + 1
    out.mkdir(parents=True, exist_ok=True)
    return out


def list_reviews(base: Path = REVIEWS_DIR) -> list[Path]:
    if not base.exists():
        return []
    dirs = [d for d in base.iterdir() if d.is_dir() and (d / "settings.json").exists()]
    return sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True)


STAGE_FILES = {"protocol": ["protocol.json"], "search": ["identified.json", "records.json"],
               "screening": ["screening.csv", "prisma.json"], "evidence": ["evidence.csv"],
               "review": ["review.md", "review.docx", "references.bib", "references.ris"]}


def reset_from(out: Path, stage: str) -> None:
    """Delete the outputs of `stage` and every later stage, so they can be redone."""
    order = list(STAGE_FILES)
    for st in order[order.index(stage):]:
        for name in STAGE_FILES[st]:
            (out / name).unlink(missing_ok=True)


def status(out: Path) -> dict[str, bool]:
    return {
        "protocol": (out / "protocol.json").exists(),
        "search": (out / "records.json").exists(),
        "screening": (out / "screening.csv").exists(),
        "evidence": (out / "evidence.csv").exists(),
        "review": (out / "review.md").exists(),
    }


# -------------------------------------------------------------------------- settings
def save_settings(out: Path, question: str, max_records: int, sources: list[str], offline: bool) -> None:
    _write_json(out / "settings.json", {
        "question": question, "max_records": max_records, "sources": sources,
        "offline": offline, "created": datetime.now().isoformat(timespec="seconds")})


def load_settings(out: Path) -> dict:
    return _read_json(out / "settings.json")


# ------------------------------------------------------------------- 1. protocol
def make_protocol(out: Path) -> Protocol:
    protocol = SearchAgent().run(load_settings(out)["question"])
    save_protocol(out, protocol)
    return protocol


def save_protocol(out: Path, protocol: Protocol) -> None:
    _write_json(out / "protocol.json", protocol.model_dump())


def load_protocol(out: Path) -> Protocol:
    return Protocol.model_validate(_read_json(out / "protocol.json"))


# --------------------------------------------------------------------- 2. search
def run_search(out: Path, log: Log = print) -> list[Paper]:
    s, protocol = load_settings(out), load_protocol(out)
    if s["offline"]:
        log("Demo mode: using the built-in example records (no database search).")
        raw = list(OFFLINE_SAMPLE)
    else:
        src = [x for x in s["sources"] if x in SOURCES] or ALL_SOURCES
        per = max(5, s["max_records"] // (len(protocol.queries) * len(src)) + 2)
        raw = []
        for q in protocol.queries:
            log(f"query: {q}")
            raw.extend(search_all(q, per, src, log=log, dedup=False))
        if not raw:
            raise RuntimeError("No records were retrieved from any database. Check the internet connection, "
                               "try other databases, or simplify the search strings in the protocol.")
    deduped = dedupe(raw)
    records = deduped[: s["max_records"]]
    _write_json(out / "identified.json", {
        "per_source": dict(Counter(p.source or "unknown" for p in raw)),
        "after_dedupe": len(deduped), "screened_pool": len(records), "demo_sample": bool(s["offline"])})
    _write_json(out / "records.json", [p.model_dump() for p in records])
    log(f"identified {len(raw)} → after de-duplication {len(deduped)} → sent to screening {len(records)}")
    return records


def load_records(out: Path) -> list[Paper]:
    return [Paper(**p) for p in _read_json(out / "records.json")]


def load_identified(out: Path) -> dict:
    return _read_json(out / "identified.json")


# ------------------------------------------------------------------ 3. screening
def run_screening(out: Path, log: Log = print) -> list[dict]:
    records = load_records(out)
    decisions = ScreeningAgent().run(load_protocol(out), records, log=log)
    by_id = {p.id: p for p in records}
    rows = [{"paper_id": d.paper_id, "title": by_id[d.paper_id].title if d.paper_id in by_id else "",
             "year": by_id[d.paper_id].year if d.paper_id in by_id else "",
             "ai_decision": d.decision, "decision": d.decision, "reason": d.reason} for d in decisions]
    save_screening(out, rows)
    return rows


def save_screening(out: Path, rows: list[dict]) -> PrismaCounts:
    """Save (possibly human-edited) decisions and recompute the PRISMA counts from them."""
    for r in rows:
        if r.get("decision") not in ("include", "exclude", "maybe"):
            raise ValueError(f"Decision for {r.get('paper_id')} must be include, exclude or maybe.")
        changed = r.get("ai_decision") and r["decision"] != r["ai_decision"]
        if changed and not str(r.get("reason", "")).startswith("Reviewer"):
            r["reason"] = f"Reviewer override (AI said {r['ai_decision']}): {r.get('reason', '')}"
    _write_csv(out / "screening.csv", rows, SCREENING_FIELDS)
    return update_prisma(out, rows)


def load_screening(out: Path) -> list[dict]:
    return _read_csv(out / "screening.csv")


def update_prisma(out: Path, rows: list[dict] | None = None) -> PrismaCounts:
    rows = rows if rows is not None else load_screening(out)
    ident = load_identified(out)
    prisma = counts_from(ident["per_source"], ident["after_dedupe"], ident["screened_pool"], rows)
    _write_json(out / "prisma.json", prisma.model_dump())
    return prisma


def load_prisma(out: Path) -> PrismaCounts:
    return PrismaCounts.model_validate(_read_json(out / "prisma.json"))


def included_papers(out: Path) -> list[Paper]:
    ids = {r["paper_id"] for r in load_screening(out) if r["decision"] == "include"}
    return [p for p in load_records(out) if p.id in ids]


# ----------------------------------------------------------------- 4. extraction
def run_extraction(out: Path, log: Log = print) -> list[EvidenceRow]:
    """Extract evidence for included papers. Rows already extracted (and possibly edited by a human)
    are kept; rows for papers no longer included are dropped; only new papers go to the model."""
    included = included_papers(out)
    if not included:
        raise RuntimeError("No papers are marked 'include'. Loosen the criteria, change decisions in the "
                           "screening table, or increase the number of records.")
    existing = {r.paper_id: r for r in load_evidence(out)} if (out / "evidence.csv").exists() else {}
    todo = [p for p in included if p.id not in existing]
    if todo:
        new = {r.paper_id: r for r in ExtractionAgent().run(load_protocol(out), todo, log=log)}
    else:
        new = {}
        log("evidence already extracted for every included paper")
    rows = [existing.get(p.id) or new[p.id] for p in included]
    save_evidence(out, [r.model_dump() for r in rows])
    return rows


def save_evidence(out: Path, rows: list[dict]) -> None:
    _write_csv(out / "evidence.csv", rows, EVIDENCE_FIELDS)


def load_evidence(out: Path) -> list[EvidenceRow]:
    return [EvidenceRow(**{k: (v or "") for k, v in r.items() if k in EVIDENCE_FIELDS})
            for r in _read_csv(out / "evidence.csv")]


def evidence_out_of_date(out: Path) -> bool:
    """True when the included set changed after the evidence table was built."""
    if not (out / "evidence.csv").exists():
        return False
    return {p.id for p in included_papers(out)} != {r.paper_id for r in load_evidence(out)}


# -------------------------------------------------------------------- 5. writing
def run_writing(out: Path, echo: bool = False, on_text: Callable[[str], None] | None = None) -> str:
    """Write the review from the (possibly human-edited) evidence table — the `--from-evidence` path."""
    rows = load_evidence(out)
    ids = {r.paper_id for r in rows}
    included = [p for p in load_records(out) if p.id in ids]
    review = WritingAgent().run(load_protocol(out), update_prisma(out), rows, included,
                                echo=echo, on_text=on_text)
    (out / "review.md").write_text(review, encoding="utf-8")
    return review


def load_review(out: Path) -> str:
    return (out / "review.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------- everything
STAGES = ["protocol", "search", "screening", "evidence", "review"]


def run_remaining(out: Path, log: Log = print, echo: bool = False,
                  on_text: Callable[[str], None] | None = None) -> None:
    """Run every stage that has not been done yet, in order."""
    done = status(out)
    if not done["protocol"]:
        log("1. Search strategy / protocol")
        make_protocol(out)
    if not done["search"]:
        log("2. Database search")
        run_search(out, log=log)
    if not done["screening"]:
        log("3. Title/abstract screening")
        run_screening(out, log=log)
    if not done["evidence"] or evidence_out_of_date(out):
        log("4. Knowledge extraction")
        run_extraction(out, log=log)
    if not done["review"]:
        log("5. Writing the review")
        run_writing(out, echo=echo, on_text=on_text)
