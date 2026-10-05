# AI Agent for Academic

**Two AI research agents in one app:** a PRISMA-style **Literature Review Agent** and an
**Academic Writing & Publication Agent**, connected so the papers your review includes become the
reference list your manuscript cites.

```
📚 Literature Review Agent        question ─► protocol ─► search ─► screen ─► extract ─► review.md
                                                                          │
                                         included papers + review text   ▼  (the "bridge")
✍️ Academic Writing Agent          notes ─► manuscript ─► journal match ─► peer review ─► response letter
                                                                                  └──────► revised manuscript
```

Built from agents **02** and **04** of the open
[Top five AI agents for research](https://github.com/AammarTufail/top_five_ai_agents_for_research)
kit by Codanics, following that kit's code layout, rules and roadmap (CLI → Streamlit app + upload + export).

---

## Start it

**Mac:** double-click **`Start AI Agent.command`**. The first time, it installs everything (a few
minutes); after that it opens the app in your browser. Paste your
[Anthropic API key](https://console.anthropic.com/) in **⚙️ Settings** (left sidebar) once.

**Windows:** double-click **`Start AI Agent.bat`**.

**By hand (any system):**

```bash
bash setup_venv.sh                       # Windows: .\setup_venv.ps1
.venv/bin/python -m streamlit run app.py # Windows: .\.venv\Scripts\python.exe -m streamlit run app.py
```

Needs Python 3.10 or newer and an Anthropic API key.

## What each agent does

### 📚 Literature Review Agent — "Autonomous Systematic Review Scientist"

| Step | Agent | Output (saved in `Outputs/Literature reviews/<question>/`) |
|------|-------|--------|
| 1 | **SearchAgent** | `protocol.json` — PICO scope, inclusion/exclusion criteria, 3–6 search strings (editable) |
| 2 | **tools.search** | `records.json`, `identified.json` — PubMed, Semantic Scholar, arXiv, Crossref; de-duplicated by DOI/title |
| 3 | **ScreeningAgent** | `screening.csv` — include / exclude / maybe + reason for every record, 10 per call; you can override any decision |
| – | **prisma.py** | `prisma.json` + flow diagram — counted by code, recomputed after every override |
| 4 | **ExtractionAgent** | `evidence.csv` — study, sample, method, key result, limitations, theme (editable) |
| 5 | **WritingAgent** | `review.md` + `review.docx` — cites only included papers by their `[id]`; `references.bib` / `.ris` for Zotero/EndNote |

### ✍️ Academic Writing & Publication Agent — "From Data to Manuscript"

| Step | Agent | Output (saved in `Outputs/Manuscripts/<project>/`) |
|------|-------|--------|
| 1 | **ManuscriptAgent** | `manuscript_v1.md/.docx` — IMRaD draft from your notes (or upload an existing paper) + AI-use declaration |
| 2 | **JournalMatchingAgent** | `journal_matches.json` — top 5 journals from the catalogue, with fit, cost, acceptance odds and tips |
| 3 | **ReviewerSimulationAgent** | `reviews.json` — 1–3 reviewers: methodologist, domain expert, statistician |
| 4 | **RevisionAgent.letter** | `response_letter.md/.docx` — point-by-point reply quoting every comment |
| 5 | **RevisionAgent.revise** | `manuscript_v2.md/.docx` — full revised manuscript, changes in **bold** |

Notes can be typed, pasted, or uploaded as Word, PDF, Markdown or text.

## The rules both agents follow (from the original kit)

- **Tools own the facts, the model owns reasoning and writing.** The writer may cite only papers the
  database search actually returned; the manuscript writer uses only facts in your notes and writes
  **[TO BE ADDED BY AUTHORS]** for anything missing.
- **PRISMA numbers are computed by code**, never generated.
- **Structured outputs** (Pydantic schemas) for every decision, so each one is data you can audit and edit.
- **Human in the loop:** edit the protocol, screening decisions, evidence table or manuscript, then
  re-run only what changed. Steps that depend on something you edited are marked ⚠️ out of date.
- **Audit trail:** every stage is saved as a file before the next one starts.

## Command line (same as the original kit)

```bash
source .venv/bin/activate
python literature_review/main.py --question "AI for breast cancer detection on mammography" --max-records 80
python literature_review/main.py --question "..." --offline                       # built-in demo papers
python literature_review/main.py --from-evidence "Outputs/Literature reviews/<folder>"   # after editing evidence.csv

python academic_writing/main.py --notes academic_writing/sample_notes.md --field "plant science"
python academic_writing/main.py --manuscript my_paper.md --field "medicine" --reviewers 2
python academic_writing/main.py --notes my_notes.md --from-review "Outputs/Literature reviews/<folder>"
```

The CLI and the web app write to the same folders, so you can start in one and continue in the other.

## Folder layout

```
ai agent for academic/
├── Start AI Agent.command / .bat   double-click launchers
├── app.py                          the web app (Streamlit): both agents + bridge + settings
├── llm.py                          the ONE file that talks to Claude: ask() and ask_structured()
├── bridge.py                       review ─► writer: reference list + background text
├── documents.py                    upload reading (Word/PDF), Word export, BibTeX/RIS
├── literature_review/              agent 02: agents.py, tools.py, prisma.py, workflow.py, main.py
├── academic_writing/               agent 04: agents.py, journals.py, workflow.py, main.py, sample_notes.md
├── requirements.txt · setup_venv.sh · setup_venv.ps1 · .env.example
└── Outputs/                        everything you make (not uploaded to GitHub)
```

## Settings (`.env`, or ⚙️ Settings in the app)

| Variable | Meaning |
|----------|---------|
| `ANTHROPIC_API_KEY` | required |
| `CLAUDE_MODEL` | `claude-opus-5-5` (default, best quality) or `claude-sonnet-5-5` (about half the price) |
| `CLAUDE_BULK_MODEL` | optional cheaper model just for screening and extraction (many small calls) |
| `SEMANTIC_SCHOLAR_API_KEY` | recommended — anonymous Semantic Scholar access is often rate-limited |
| `NCBI_EMAIL`, `NCBI_API_KEY` | polite / faster PubMed access |

Every call uses adaptive thinking with the effort level the original kit chose per task (`low` for
protocol and screening, `medium` for extraction and journal matching, `high` for writing and critique),
streams long outputs, and opts in to Anthropic's server-side refusal fallback.

## Changes from the original kit

- One web app for both agents, plus the review → writer bridge the kit's guide suggests ("bundle with
  the Literature Review Agent").
- PRISMA fixes: records dropped by the record cap are no longer counted as duplicates; duplicates are
  counted across all databases before de-duplication; exclusion reasons are grouped by their content;
  human overrides are labelled in the screening log.
- Every included paper gets exactly one evidence row; rows for IDs the search never returned are dropped.
- Journal catalogue extended with breast cancer, surgical oncology, radiology, oncology and
  digital-health journals; editable in the app; live fees and open-access status from
  [OpenAlex](https://openalex.org) (`journals_live.json`). Values not known are left empty, not guessed.
- Word export of every document, BibTeX/RIS export of included papers, Word/PDF upload.
- Default model updated to Claude Opus 5.5.
- If no database returns anything, the review stops with a message instead of silently using demo papers.

## Please read

- **These are drafts.** Check every citation, number and claim against the original papers before use.
- Text you enter is sent to the Anthropic API. Do not enter identifiable patient information.
- Journal fees, impact and acceptance odds are indicative; confirm on the journal's website.
- `.env` (your API key) and `Outputs/` (your work) are in `.gitignore` and never leave your computer via git.

## Credits

Agent design, prompts and pipeline structure: **Codanics — “Top five AI agents for research”**
(<https://github.com/AammarTufail/top_five_ai_agents_for_research>, course
<https://codanics.com/courses/python-ka-chilla-build-ai-agents/>). That repository does not state a
licence; this adaptation keeps the attribution in every file derived from it. This repository is
released under the MIT License (see `LICENSE`).
