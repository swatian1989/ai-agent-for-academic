"""
AI Academic Writing & Publication Agent — "From Data to Manuscript" (command-line version)
========================================================================================
notes ─► manuscript ─► journal matching ─► reviewer simulation ─► response letter + revised manuscript

Usage (from the app folder, with the virtual environment active)
    python academic_writing/main.py --notes academic_writing/sample_notes.md --field "plant science"
    python academic_writing/main.py --notes my_notes.md --field "medicine" --reviewers 2 --references refs.md
    python academic_writing/main.py --manuscript existing_paper.md --field "AI"   # skip drafting; review a paper
    python academic_writing/main.py --notes my_notes.md --from-review "Outputs/Literature reviews/<folder>"
                                                         # cite the papers included by the Literature Review Agent

Outputs: Outputs/Manuscripts/<slug>/ manuscript_v1.md, journal_matches.json, reviews.json,
         response_letter.md, manuscript_v2.md — the same folders the web app shows.

Adapted from the Codanics "Top five AI agents for research" kit (agent 04).
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252; we print → ✓ etc.
    sys.stdout.reconfigure(encoding="utf-8")
import bridge  # noqa: E402
from academic_writing import workflow as wf  # noqa: E402

app = typer.Typer(add_completion=False)
console = Console()

BANNER = """[bold cyan]AI Academic Writing & Publication Agent[/] — From Data to Manuscript
[dim]AI Agent for Academic · adapted from the Codanics "Top five AI agents for research" kit[/]"""


@app.command()
def run(
    notes: Path = typer.Option(None, help="Markdown/text file with study notes and results"),
    manuscript: Path = typer.Option(None, help="Existing manuscript (.md) to review instead of drafting"),
    references: Path = typer.Option(None, help="Optional reference list file the writer may cite"),
    from_review: Path = typer.Option(None, help="Literature-review output folder: cite its included papers"),
    field: str = typer.Option("multidisciplinary", help="Research field, e.g. 'breast surgery'"),
    reviewers: int = typer.Option(3, min=1, max=3),
    echo: bool = typer.Option(True),
):
    console.print(Panel(BANNER, expand=False))
    if not notes and not manuscript:
        raise typer.BadParameter("Provide --notes or --manuscript")
    src = manuscript or notes
    refs = references.read_text(encoding="utf-8") if references else ""
    background = ""
    if from_review:
        refs = (refs + "\n\n" if refs else "") + bridge.references_from_review(from_review)
        background = bridge.background_from_review(from_review)
        console.print(f"  imported references from [bold]{from_review.name}[/]")

    out = wf.new_project_dir(src.stem)
    wf.save_inputs(out, project=src.stem, field=field, reviewers=reviewers,
                   mode="manuscript" if manuscript else "notes",
                   notes=notes.read_text(encoding="utf-8") if notes else "",
                   manuscript=manuscript.read_text(encoding="utf-8") if manuscript else "",
                   references=refs, background=background,
                   source_review=str(from_review) if from_review else None)

    # 1) Manuscript ---------------------------------------------------------------
    console.rule("[bold]1. Manuscript")
    if manuscript:
        console.print(f"  using existing manuscript {manuscript}")
    wf.run_manuscript(out, echo=echo)

    # 2) Journal matching ---------------------------------------------------------
    console.rule("[bold]2. Journal matching")
    ranking = wf.run_journal_matching(out)
    t = Table(title="Recommended journals")
    for c in ("journal", "scope fit", "impact", "OA", "APC $", "acceptance"):
        t.add_column(c)
    for m in ranking.matches:
        t.add_row(m.journal, str(m.scope_fit), m.impact_band, m.open_access,
                  str(m.estimated_apc_usd or "-"), m.acceptance_probability)
    console.print(t)

    # 3) Reviewer simulation ------------------------------------------------------
    console.rule(f"[bold]3. Simulated peer review ({reviewers} reviewers)")
    reviews = wf.run_reviews(out)
    for r in reviews.reviews:
        console.print(f"  [bold]{r.reviewer}[/] → {r.recommendation}")
        for c in r.comments[:4]:
            console.print(f"     {c.number}. [{c.severity}] {c.comment[:140]}")

    # 4) Revision -----------------------------------------------------------------
    console.rule("[bold]4. Response letter")
    wf.run_letter(out, echo=echo)
    console.rule("[bold]5. Revised manuscript")
    wf.run_revision(out, echo=False)
    console.print(Panel(f"Done. Outputs in [bold]{out}[/]", style="green"))


if __name__ == "__main__":
    app()
