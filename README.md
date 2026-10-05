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

Needs Python 3.10 or newer and one API key: Claude (paid) or a free Google Gemini / OpenRouter key.

## Free AI options (no payment)

The agents were built for **Claude** (paid per use, best quality). In **⚙️ Settings → AI provider** you
can switch to a free online model instead — nothing to install, works on your computer and online:

| Provider | Key | Free limits | Keep in mind |
|---|---|---|---|
| **Claude** (Anthropic) | [console.anthropic.com](https://console.anthropic.com/settings/keys) — paid credit | pay per use | best quality; data not used for training |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — free, no card | daily limits set by Google | on the free tier Google may use what you send to improve its products |
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) — free | free models (`…:free`): about 50 requests/day (~3 full runs) | press “Load available models”; some free models log prompts |

Free models follow the same rules (cite only retrieved papers, PRISMA by code, `[TO BE ADDED BY AUTHORS]`).
Because they cannot guarantee structured output like Claude, the app asks them for JSON, checks it, and
asks once more to repair it if needed. Expect weaker writing than Claude, and do not send unpublished or
patient-related text to a free tier. Groq's free tier was left out: its 8,000-tokens-per-minute limit is
too small for writing a review.

## Put it online (Streamlit Community Cloud, free)

1. Open <https://share.streamlit.io/deploy?repository=swatian1989/ai-agent-for-academic&branch=main&mainModule=app.py>
   and sign in with GitHub (allow access to private repositories when asked).
2. Check: repository `swatian1989/ai-agent-for-academic`, branch `main`, main file `app.py`.
3. **Advanced settings** → Python **3.12** → **Secrets**: paste the contents of
   [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) and fill in your values
   (keep `AI_AGENT_CLOUD = "1"`). Then **Deploy**.
4. Share it: because the GitHub repo is private, the app is private too — invite people by email with
   the app's **Share** button (they sign in with Google or an emailed link). The free plan allows one
   private app.

What changes online (`AI_AGENT_CLOUD = "1"`):

| | On your computer | Online |
|---|---|---|
| API key | saved in `.env` | from the app's secrets (your key), or each visitor's own key, kept only for their browser session |
| Password | — | optional `APP_PASSWORD` asked once per session (recommended when using your key) |
| Your files | `Outputs/` folder, permanent | a private workspace per visitor (`?ws=…` in the address), **deleted when the app restarts or sleeps** — download Word files or a ZIP |
| Journal catalogue | editable | read-only (shared by everyone) |

The app sleeps after about 12 hours without visitors; opening it wakes it up in under a minute.

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
| `AI_PROVIDER` | `anthropic` (default), `gemini` or `openrouter` |
| `ANTHROPIC_API_KEY` | for Claude |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | for free Google Gemini (default model `gemini-3.8-flash`) |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | for free OpenRouter models |
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
