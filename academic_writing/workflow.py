"""
workflow.py — the publication pipeline as resumable stages, each saved to disk.

    notes ─► manuscript_v1 ─► journal matching ─► reviewer simulation ─► response letter + manuscript_v2

Both the command-line tool (main.py) and the web app (app.py) call these functions. One folder per
manuscript project:

    settings.json        project name, field, number of reviewers, mode
    notes.md             the authors' notes and results (mode "notes")
    references.md        references the writer may cite (typed, uploaded or imported from a review)
    background.md        optional: the systematic review text, used for Introduction/Discussion
    manuscript_v1.md     the draft — or your existing manuscript (mode "manuscript"); editable
    journal_matches.json ranked journals
    reviews.json         simulated peer reviews
    response_letter.md   point-by-point response
    manuscript_v2.md     revised manuscript, changes in **bold**
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from slugify import slugify

from .agents import (JournalMatchingAgent, JournalRanking, ManuscriptAgent, ReviewerSimulationAgent, ReviewSet,
                     RevisionAgent)

APP_DIR = Path(__file__).resolve().parent.parent
MANUSCRIPTS_DIR = APP_DIR / "Outputs" / "Manuscripts"
STAGES = ["manuscript", "journals", "reviews", "letter", "revision"]
FILES = {"manuscript": "manuscript_v1.md", "journals": "journal_matches.json", "reviews": "reviews.json",
         "letter": "response_letter.md", "revision": "manuscript_v2.md"}
DEPENDS_ON = {"journals": "manuscript", "reviews": "manuscript", "letter": "reviews", "revision": "reviews"}

OnText = Callable[[str], None] | None


def _read(out: Path, name: str) -> str:
    p = out / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write(out: Path, name: str, text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- folders
def new_project_dir(name: str, base: Path = MANUSCRIPTS_DIR) -> Path:
    stem = slugify(name)[:60] or "manuscript"
    out, n = base / stem, 2
    while out.exists() and any(out.iterdir()):
        out, n = base / f"{stem}-{n}", n + 1
    out.mkdir(parents=True, exist_ok=True)
    return out


def list_projects(base: Path = MANUSCRIPTS_DIR) -> list[Path]:
    if not base.exists():
        return []
    dirs = [d for d in base.iterdir() if d.is_dir() and (d / "settings.json").exists()]
    return sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True)


def status(out: Path) -> dict[str, bool]:
    return {stage: (out / f).exists() for stage, f in FILES.items()}


def out_of_date(out: Path) -> dict[str, bool]:
    """A stage is out of date when the file it was built from changed after it was made."""
    res: dict[str, bool] = {}
    for stage, dep in DEPENDS_ON.items():  # ordered: a stage is also stale when what it depends on is stale
        a, b = out / FILES[stage], out / FILES[dep]
        newer = a.exists() and b.exists() and b.stat().st_mtime > a.stat().st_mtime + 1
        res[stage] = a.exists() and (newer or res.get(dep, False))
    return res


# ---------------------------------------------------------------------------- inputs
def save_inputs(out: Path, *, project: str, field: str, reviewers: int, mode: str, notes: str = "",
                manuscript: str = "", references: str = "", background: str = "",
                source_review: str | None = None) -> None:
    if mode not in ("notes", "manuscript"):
        raise ValueError("mode must be 'notes' or 'manuscript'")
    _write(out, "settings.json", json.dumps({
        "project": project, "field": field, "reviewers": int(reviewers), "mode": mode,
        "source_review": source_review, "created": datetime.now().isoformat(timespec="seconds")}, indent=2))
    _write(out, "notes.md", notes)
    _write(out, "references.md", references)
    _write(out, "background.md", background)
    if mode == "manuscript":
        _write(out, FILES["manuscript"], manuscript)


def load_inputs(out: Path) -> dict:
    s = json.loads(_read(out, "settings.json"))
    s.update(notes=_read(out, "notes.md"), references=_read(out, "references.md"),
             background=_read(out, "background.md"))
    return s


# ------------------------------------------------------------------- 1. manuscript
def run_manuscript(out: Path, echo: bool = False, on_text: OnText = None) -> str:
    s = load_inputs(out)
    if s["mode"] == "manuscript":
        return load_manuscript(out)
    if not s["notes"].strip():
        raise RuntimeError("Add your study notes and results first.")
    ms = ManuscriptAgent().run(s["notes"], s["field"], s["references"], s["background"],
                               echo=echo, on_text=on_text)
    save_manuscript(out, ms)
    return ms


def save_manuscript(out: Path, text: str) -> None:
    _write(out, FILES["manuscript"], text)


def load_manuscript(out: Path) -> str:
    return _read(out, FILES["manuscript"])


# -------------------------------------------------------------- 2. journal matching
def run_journal_matching(out: Path) -> JournalRanking:
    ranking = JournalMatchingAgent().run(load_manuscript(out))
    _write(out, FILES["journals"], ranking.model_dump_json(indent=2))
    return ranking


def load_ranking(out: Path) -> JournalRanking:
    return JournalRanking.model_validate_json(_read(out, FILES["journals"]))


# ----------------------------------------------------------- 3. reviewer simulation
def run_reviews(out: Path) -> ReviewSet:
    reviews = ReviewerSimulationAgent().run(load_manuscript(out), load_inputs(out)["reviewers"])
    _write(out, FILES["reviews"], reviews.model_dump_json(indent=2))
    return reviews


def load_reviews(out: Path) -> ReviewSet:
    return ReviewSet.model_validate_json(_read(out, FILES["reviews"]))


# ----------------------------------------------------------------- 4–5. revision
def run_letter(out: Path, echo: bool = False, on_text: OnText = None) -> str:
    text = RevisionAgent().letter(load_manuscript(out), load_reviews(out), echo=echo, on_text=on_text)
    _write(out, FILES["letter"], text)
    return text


def run_revision(out: Path, echo: bool = False, on_text: OnText = None) -> str:
    text = RevisionAgent().revise(load_manuscript(out), load_reviews(out), echo=echo, on_text=on_text)
    _write(out, FILES["revision"], text)
    return text


def read_output(out: Path, stage: str) -> str:
    return _read(out, FILES[stage])


# ------------------------------------------------------------------- everything
def run_remaining(out: Path, log: Callable[[str], None] = print, echo: bool = False,
                  on_text_for: Callable[[str], OnText] = lambda stage: None) -> None:
    """Run every stage that is missing or out of date, in order."""
    def needed(stage: str) -> bool:
        return not status(out)[stage] or out_of_date(out).get(stage, False)

    if needed("manuscript"):
        log("1. Manuscript")
        run_manuscript(out, echo=echo, on_text=on_text_for("manuscript"))
    if needed("journals"):
        log("2. Journal matching")
        run_journal_matching(out)
    if needed("reviews"):
        log("3. Simulated peer review")
        run_reviews(out)
    if needed("letter"):
        log("4. Response letter")
        run_letter(out, echo=echo, on_text=on_text_for("letter"))
    if needed("revision"):
        log("5. Revised manuscript")
        run_revision(out, echo=False, on_text=on_text_for("revision"))
