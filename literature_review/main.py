"""
AI Literature Review Agent — "Autonomous Systematic Review Scientist" (command-line version)
==========================================================================================
question ─► protocol ─► search (4 databases) ─► screen ─► extract ─► PRISMA counts ─► review.md

Usage (from the app folder, with the virtual environment active)
    python literature_review/main.py --question "AI for breast cancer detection on mammography"
    python literature_review/main.py --question "..." --max-records 80 --sources arxiv,pubmed
    python literature_review/main.py --question "..." --offline                 # demo sample, no search
    python literature_review/main.py --question "..." --from-evidence "Outputs/Literature reviews/<folder>"

Outputs: Outputs/Literature reviews/<slug>/  protocol.json, records.json, screening.csv, evidence.csv,
         prisma.json, review.md — the same folders the web app shows, so you can switch between them.

Adapted from the Codanics "Top five AI agents for research" kit (agent 02).
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
from literature_review import workflow as wf  # noqa: E402

app = typer.Typer(add_completion=False)
console = Console()

BANNER = """[bold cyan]AI Literature Review Agent[/] — Autonomous Systematic Review Scientist
[dim]AI Agent for Academic · adapted from the Codanics "Top five AI agents for research" kit[/]"""


@app.command()
def run(
    question: str = typer.Option(None, help="The review question / topic"),
    max_records: int = typer.Option(60, help="Max records to screen"),
    sources: str = typer.Option(",".join(wf.ALL_SOURCES)),
    offline: bool = typer.Option(False, help="Use built-in demo records"),
    from_evidence: Path = typer.Option(None, help="Existing output folder: skip to writing using its evidence.csv"),
    echo: bool = typer.Option(True, help="Stream the review to the console"),
):
    console.print(Panel(BANNER, expand=False))
    log = lambda m: console.print(f"  {m}")  # noqa: E731

    # --- resume mode: human edited evidence.csv, just re-write the review -------------
    if from_evidence:
        console.rule("[bold]Re-writing review from edited evidence")
        wf.run_writing(from_evidence, echo=echo)
        console.print(Panel(f"Done → {from_evidence / 'review.md'}", style="green"))
        return

    if not question:
        raise typer.BadParameter("Provide --question (or --from-evidence to re-write an existing review)")
    out = wf.new_review_dir(question)
    wf.save_settings(out, question, max_records, [s.strip() for s in sources.split(",") if s.strip()], offline)

    console.rule("[bold]1. Search strategy / protocol")
    protocol = wf.make_protocol(out)
    console.print(f"  [bold]{protocol.review_title}[/]\n  Q: {protocol.research_question}")
    console.print(f"  include: {protocol.inclusion_criteria}\n  exclude: {protocol.exclusion_criteria}")

    console.rule("[bold]2. Database search")
    try:
        wf.run_search(out, log=log)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/] (or re-run with --offline for the demo sample)")
        raise typer.Exit(1)

    console.rule("[bold]3. Title/abstract screening")
    wf.run_screening(out, log=log)
    prisma = wf.load_prisma(out)
    console.print(prisma.flow_markdown())

    console.rule("[bold]4. Knowledge extraction")
    try:
        rows = wf.run_extraction(out, log=log)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    t = Table(title="Evidence table (first rows)")
    for c in ("study", "dataset_or_sample", "method", "key_result"):
        t.add_column(c, max_width=40)
    for r in rows[:10]:
        t.add_row(r.study, r.dataset_or_sample, r.method, r.key_result)
    console.print(t)

    console.rule("[bold]5. Writing the review")
    wf.run_writing(out, echo=echo)
    console.print(Panel(f"Done. Outputs in [bold]{out}[/]\nEdit evidence.csv and re-run with "
                        f"--from-evidence \"{out}\" to regenerate the review.", style="green"))


if __name__ == "__main__":
    app()
