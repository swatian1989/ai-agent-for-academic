"""
app.py — AI Agent for Academic: two research agents in one web app.

    📚 Literature Review Agent           question ─► protocol ─► search ─► screen ─► extract ─► review
    ✍️ Academic Writing & Publication     notes ─► manuscript ─► journals ─► peer review ─► letter + revision
    🔗 Bridge                             papers included in a review become the writer's reference list

Run:  streamlit run app.py      (or double-click "Start AI Agent.command" on a Mac)
Online: deploy app.py on Streamlit Community Cloud with the secrets in .streamlit/secrets.toml.example

Adapted from the Codanics "Top five AI agents for research" kit (agents 02 and 04).
"""
from __future__ import annotations

import hmac
import io
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import bridge  # noqa: E402
import documents  # noqa: E402
import llm  # noqa: E402
from academic_writing import journals as jr  # noqa: E402
from academic_writing import workflow as aw  # noqa: E402
from academic_writing.agents import ReviewSet  # noqa: E402
from literature_review import workflow as lr  # noqa: E402
from literature_review.agents import Protocol  # noqa: E402

st.set_page_config(page_title="AI Agent for Academic", page_icon="🎓", layout="wide")

try:  # loading Streamlit secrets also exports the root-level ones as environment variables
    len(st.secrets)
except Exception:  # no secrets file: running on your own computer
    pass
# Hosted = running on Streamlit Community Cloud (or any shared server): one disk shared by every visitor,
# wiped on restart. Then keys stay in the browser session, never on disk, and each visitor gets a workspace.
HOSTED = os.getenv("AI_AGENT_CLOUD") == "1" or str(APP_DIR).startswith("/mount/src")
ss = st.session_state


def workspace() -> Path:
    """Your own computer: ./Outputs. Hosted: a private workspace whose id lives in the page address
    (?ws=…), so a bookmark brings you back to your files while the server keeps running."""
    if not HOSTED:
        return APP_DIR / "Outputs"
    ws = st.query_params.get("ws", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,40}", ws or ""):
        ws = ss.setdefault("workspace_id", uuid.uuid4().hex)
        st.query_params["ws"] = ws
    return APP_DIR / "Outputs" / "workspaces" / ws


OUTPUTS = workspace()
REVIEWS = OUTPUTS / "Literature reviews"
PROJECTS = OUTPUTS / "Manuscripts"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SOURCE_LABELS = {"arxiv": "arXiv", "semantic_scholar": "Semantic Scholar", "pubmed": "PubMed",
                 "crossref": "Crossref"}
SAMPLE_NOTES = (APP_DIR / "academic_writing" / "sample_notes.md").read_text(encoding="utf-8")


# =============================================================================== helpers
def save_env(updates: dict[str, str]) -> None:
    """Write settings to the app's .env file (kept private: never uploaded to GitHub)."""
    lines = llm.ENV_FILE.read_text(encoding="utf-8").splitlines() if llm.ENV_FILE.exists() else []
    out, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    llm.ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(llm.ENV_FILE, 0o600)
    for k, v in updates.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    llm.reset_client()


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def zip_folder(folder: Path) -> bytes:
    """Everything in one project folder as a ZIP (Word copies included)."""
    for md in folder.glob("*.md"):
        ensure_docx(md)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.iterdir()):
            if f.is_file():
                z.write(f, arcname=f"{folder.name}/{f.name}")
    return buf.getvalue()


def password_gate() -> None:
    """If the owner set APP_PASSWORD (in secrets or .env), ask for it once per browser session."""
    pw = os.getenv("APP_PASSWORD", "")
    if not pw or ss.get("authed"):
        return
    st.title("🎓 AI Agent for Academic")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Enter", type="primary"):
            if hmac.compare_digest(entered.encode(), pw.encode()):
                ss.authed = True
                st.rerun()
            st.error("Wrong password.")
    st.stop()


class LiveText:
    """Shows streamed model output as it is written."""

    def __init__(self, container):
        self.ph = container.empty()
        self.buf, self.last = "", 0.0

    def reset(self):
        self.buf = ""
        return self

    def __call__(self, chunk: str) -> None:
        self.buf += chunk
        if time.time() - self.last > 0.3:
            self.ph.markdown(self.buf + " ▌")
            self.last = time.time()


def run_step(label: str, fn, *, needs_key: bool = True, stream: bool = False) -> bool:
    """Run one pipeline stage inside a live status box. `fn(log, live)`; returns True on success."""
    if needs_key and not llm.has_api_key():
        st.error("Add your Anthropic API key in ⚙️ Settings (left sidebar) first.")
        return False
    with st.status(f"{label} …", expanded=True) as box:
        live = LiveText(box) if stream else None
        try:
            fn(box.write, live)
        except Exception as exc:  # show a plain-language message, keep the app alive
            box.update(label=f"{label} — stopped", state="error", expanded=True)
            st.error(llm.friendly_error(exc))
            return False
        box.update(label=f"{label} — done", state="complete", expanded=False)
    return True


def step_header(n: int, title: str, done: bool, stale: bool = False) -> None:
    mark = "⚠️" if stale else ("✅" if done else "⬜")
    st.markdown(f"### {mark} Step {n} · {title}")


def progress_line(labels: list[str], done: list[bool]) -> None:
    st.markdown("  →  ".join(f"{'✅' if d else '⬜'} {l}" for l, d in zip(labels, done)))


def ensure_docx(md_path: Path) -> Path:
    """Keep a Word copy next to every Markdown deliverable, so it opens with a double-click."""
    docx_path = md_path.with_suffix(".docx")
    if md_path.exists() and (not docx_path.exists() or docx_path.stat().st_mtime < md_path.stat().st_mtime):
        docx_path.write_bytes(documents.markdown_to_docx(md_path.read_text(encoding="utf-8")))
    return docx_path


def download_pair(label: str, text: str, stem: str, key: str) -> None:
    c1, c2 = st.columns(2)
    c1.download_button(f"⬇ {label} — Word", documents.markdown_to_docx(text), file_name=f"{stem}.docx",
                       mime=DOCX, key=f"{key}_docx", width="stretch")
    c2.download_button(f"⬇ {label} — Markdown", text, file_name=f"{stem}.md", mime="text/markdown",
                       key=f"{key}_md", width="stretch")


def lines(text: str) -> list[str]:
    return [x.strip() for x in text.splitlines() if x.strip()]


def mode_switch(key: str, options: list[str]) -> str:
    """A radio whose value can be changed programmatically (via ss[key + '_next']) before it is drawn."""
    if key + "_next" in ss:
        ss[key] = ss.pop(key + "_next")
    return st.radio("Choose", options, horizontal=True, key=key, label_visibility="collapsed")


# =============================================================================== sidebar
def sidebar() -> None:
    with st.sidebar:
        st.markdown("## 🎓 AI Agent for Academic")
        st.caption("Literature Review Agent + Academic Writing & Publication Agent")
        key_ok = llm.has_api_key()
        if ss.get("user_api_key"):
            st.markdown("**API key:** ✅ your own (this session only)")
        elif key_ok:
            st.markdown("**API key:** ✅ provided by the app owner" if HOSTED else "**API key:** ✅ saved")
        else:
            st.markdown("**API key:** ❌ not set yet")
        st.markdown(f"**Model:** {llm.MODEL_CHOICES.get(llm.model_for(), llm.model_for()).split(' — ')[0]}")
        with st.expander("⚙️ Settings", expanded=not key_ok):
            with st.form("settings"):
                key = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-…",
                                    help=("Create one at console.anthropic.com → API keys. Online it is kept only "
                                          "for this browser session and never saved." if HOSTED else
                                          "Create one at console.anthropic.com → API keys. It is stored only in "
                                          "this folder's private .env file.") + " Leave empty to keep the current key.")
                models = list(llm.MODEL_CHOICES)
                cur = llm.model_for()
                model = st.selectbox("Model for writing & critique", models,
                                     index=models.index(cur) if cur in models else 0,
                                     format_func=llm.MODEL_CHOICES.get)
                bulk_opts = ["same"] + models
                cur_bulk = llm.model_for("bulk") if llm.model_for("bulk") != cur else "same"
                bulk = st.selectbox("Model for screening & extraction (many small calls)", bulk_opts,
                                    index=bulk_opts.index(cur_bulk) if cur_bulk in bulk_opts else 0,
                                    format_func=lambda m: "Same as above" if m == "same" else llm.MODEL_CHOICES[m])
                if not HOSTED:  # online, the owner sets these in the app's secrets
                    s2 = st.text_input("Semantic Scholar API key (optional, avoids rate limits)", type="password",
                                       value=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""))
                    email = st.text_input("Your email for PubMed (NCBI asks for one)",
                                          value=os.getenv("NCBI_EMAIL", ""))
                if st.form_submit_button("Save settings", type="primary"):
                    bulk_model = "" if bulk == "same" else bulk
                    if HOSTED:  # this browser session only — never written to the shared disk
                        if key.strip():
                            ss.user_api_key = key.strip()
                        ss.user_model, ss.user_bulk_model = model, bulk_model
                    else:
                        updates = {"CLAUDE_MODEL": model, "CLAUDE_BULK_MODEL": bulk_model,
                                   "SEMANTIC_SCHOLAR_API_KEY": s2.strip(), "NCBI_EMAIL": email.strip()}
                        if key.strip():
                            updates["ANTHROPIC_API_KEY"] = key.strip()
                        save_env(updates)
                    st.rerun()
        st.divider()
        if HOSTED:
            st.markdown("**Your files are in temporary online storage**")
            st.caption("They are deleted when the app restarts or sleeps. Download the Word files, or a ZIP "
                       "from 📁 My files, before you leave. Bookmark this page to come back to your workspace.")
        else:
            st.markdown("**Everything you make is saved in**")
            st.code(str(OUTPUTS), language=None)
            if st.button("📂 Open the Outputs folder", width="stretch"):
                open_folder(OUTPUTS)


# =============================================================================== home
def home_tab() -> None:
    st.title("🎓 AI Agent for Academic")
    st.markdown(
        "Two AI research agents in one app. Use them separately, or one after the other: "
        "**review the literature first, then write your paper citing the papers the review found.**")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("#### 📚 Literature Review Agent\n*“Autonomous Systematic Review Scientist”*")
        st.markdown(
            "1. **Protocol** — turns your question into PICO, inclusion/exclusion criteria and search strings\n"
            "2. **Search** — PubMed, Semantic Scholar, arXiv and Crossref; duplicates removed\n"
            "3. **Screening** — include / exclude / maybe with a reason for every paper (you can change any)\n"
            "4. **Extraction** — evidence table: sample, method, key result, limitations (editable)\n"
            "5. **Review** — a PRISMA-style review that cites only the included papers")
    with c2, st.container(border=True):
        st.markdown("#### ✍️ Academic Writing & Publication Agent\n*“From Data to Manuscript”*")
        st.markdown(
            "1. **Manuscript** — full IMRaD draft from your notes and results (or upload your own paper)\n"
            "2. **Journal matching** — top 5 journals with fit, cost and acceptance odds\n"
            "3. **Peer review** — 3 simulated reviewers: methodologist, domain expert, statistician\n"
            "4. **Response letter** — point-by-point reply to every comment\n"
            "5. **Revised manuscript** — with every change in **bold**")
    st.markdown("#### How to start")
    st.markdown(
        "1. Open **⚙️ Settings** in the left sidebar and paste your Anthropic API key (once only).\n"
        "2. Go to the **📚 Literature Review** tab, type your question and press *Create review*.\n"
        "3. When the review is done, press **“Use these papers in the Writing Agent”**, then open the "
        "**✍️ Academic Writing** tab, add your study notes and results, and press *Create project*.\n"
        + ("4. Download each result as Word (online storage is temporary)." if HOSTED else
           "4. Every result is saved automatically (Word + Markdown) in the **Outputs** folder."))
    st.info(
        "**Rules these agents follow** — numbers in the PRISMA flow are counted by code, not by the AI · "
        "the AI may only cite papers that the database search actually returned · missing facts are written "
        "as **[TO BE ADDED BY AUTHORS]** instead of being invented · an AI-use declaration is added to "
        "every manuscript.")
    st.warning(
        "**Please check before you use anything.** These are drafts. Verify every citation, number and claim "
        "against the original papers. Text you enter is sent to Anthropic's API to generate the drafts — do not "
        "paste patient names, IC numbers or other identifiable patient information.")
    st.caption("Based on the open-source “Top five AI agents for research” kit by Codanics "
               "(github.com/AammarTufail/top_five_ai_agents_for_research), agents 02 and 04.")


# =============================================================================== literature review
def literature_tab() -> None:
    st.header("📚 Literature Review Agent")
    st.caption("“Autonomous Systematic Review Scientist” — PRISMA-style search → screen → extract → write")
    reviews = lr.list_reviews(REVIEWS)
    choice = mode_switch("lr_mode", ["➕ New review", "📂 Open a saved review"])

    if choice.startswith("➕"):
        with st.form("lr_new"):
            question = st.text_area("Your review question", height=80, placeholder=(
                "e.g. Deep learning for breast cancer detection combining mammography and ultrasound"))
            c1, c2 = st.columns([1, 2])
            max_records = c1.number_input("Maximum records to screen", 10, 500, 60, step=10,
                                          help="More records = better recall, but more time and cost.")
            sources = c2.multiselect("Databases", lr.ALL_SOURCES, default=lr.ALL_SOURCES,
                                     format_func=SOURCE_LABELS.get)
            how = st.radio("How should it run?", ["Step by step — I check each stage", "All 5 steps automatically"],
                           horizontal=True)
            offline = st.checkbox("Demo mode — use 6 built-in example papers instead of searching (quick test only)")
            if st.form_submit_button("Create review", type="primary"):
                if len(question.strip()) < 10:
                    st.error("Please write a review question (at least a few words).")
                elif not sources and not offline:
                    st.error("Choose at least one database.")
                else:
                    out = lr.new_review_dir(question.strip(), REVIEWS)
                    lr.save_settings(out, question.strip(), int(max_records), sources, offline)
                    ss.lr_dir, ss.lr_mode_next = str(out), "📂 Open a saved review"
                    ss.lr_autorun = how.startswith("All")
                    st.rerun()
        return

    if not reviews:
        st.info("No saved reviews yet — choose “New review”.")
        return
    paths = [str(p) for p in reviews]
    idx = paths.index(ss.lr_dir) if ss.get("lr_dir") in paths else 0
    sel = st.selectbox("Saved reviews (newest first)", paths, index=idx,
                       format_func=lambda p: f"{lr.load_settings(Path(p))['question'][:110]}  ·  {Path(p).name}")
    ss.lr_dir = sel
    render_review(Path(sel))


def render_review(out: Path) -> None:
    s, done = lr.load_settings(out), lr.status(out)
    st.subheader(s["question"])
    progress_line(["Protocol", "Search", "Screening", "Evidence", "Review"], list(done.values()))

    def run_all(log, live):
        lr.run_remaining(out, log=log, on_text=live)

    if ss.pop("lr_autorun", False) or st.button("▶ Run all remaining steps", type="primary", key="lr_all",
                                                disabled=all(done.values()) and not lr.evidence_out_of_date(out)):
        if run_step("Running the literature review", run_all, stream=True):
            st.rerun()
    st.divider()

    # ---- 1. protocol ---------------------------------------------------------------------
    step_header(1, "Protocol — criteria and search strings", done["protocol"])
    if not done["protocol"]:
        if st.button("Create the protocol", key="lr_p"):
            if run_step("Writing the protocol", lambda log, live: lr.make_protocol(out)):
                st.rerun()
        return
    p = lr.load_protocol(out)
    st.markdown(f"**{p.review_title}**  \n{p.research_question}")
    st.markdown(f"**Scope (PICO):** {p.pico_or_scope}")
    c1, c2 = st.columns(2)
    c1.markdown("**Include if**\n" + "\n".join(f"- {x}" for x in p.inclusion_criteria))
    c2.markdown("**Exclude if**\n" + "\n".join(f"- {x}" for x in p.exclusion_criteria))
    st.markdown("**Search strings**\n" + "\n".join(f"- `{q}`" for q in p.queries))
    with st.expander("✏️ Edit the protocol"):
        with st.form("lr_edit_protocol"):
            title = st.text_input("Review title", p.review_title)
            pico = st.text_area("Scope (PICO)", p.pico_or_scope)
            inc = st.text_area("Inclusion criteria (one per line)", "\n".join(p.inclusion_criteria))
            exc = st.text_area("Exclusion criteria (one per line)", "\n".join(p.exclusion_criteria))
            qs = st.text_area("Search strings (one per line)", "\n".join(p.queries))
            if done["search"]:
                st.caption("Saving clears the search and later steps, because they were based on the old protocol.")
            if st.form_submit_button("Save protocol"):
                lr.save_protocol(out, Protocol(review_title=title, research_question=p.research_question,
                                               pico_or_scope=pico, inclusion_criteria=lines(inc),
                                               exclusion_criteria=lines(exc), queries=lines(qs) or p.queries,
                                               year_from=p.year_from))
                lr.reset_from(out, "search")
                st.rerun()

    # ---- 2. search -----------------------------------------------------------------------
    step_header(2, "Database search", done["search"])
    if not done["search"]:
        if st.button("Search the databases", key="lr_s"):
            if run_step("Searching databases", lambda log, live: lr.run_search(out, log=log), needs_key=False):
                st.rerun()
        return
    ident, records = lr.load_identified(out), lr.load_records(out)
    if ident.get("demo_sample"):
        st.warning("Demo mode: these are built-in example records, not a real search. Do not use for a real review.")
    total = sum(ident["per_source"].values())
    m = st.columns(4)
    m[0].metric("Records found", total)
    m[1].metric("Duplicates removed", total - ident["after_dedupe"])
    m[2].metric("Over the record cap", ident["after_dedupe"] - ident["screened_pool"])
    m[3].metric("Sent to screening", ident["screened_pool"])
    st.caption("Found per database: " + ", ".join(f"{SOURCE_LABELS.get(k, k)} {v}"
                                                 for k, v in ident["per_source"].items()))
    with st.expander(f"See the {len(records)} records"):
        st.dataframe(pd.DataFrame([{"id": r.id, "title": r.title, "year": r.year, "journal/venue": r.venue,
                                    "database": SOURCE_LABELS.get(r.source, r.source), "citations": r.citations,
                                    "link": r.url} for r in records]),
                     column_config={"link": st.column_config.LinkColumn("link")}, hide_index=True, width="stretch")
        if st.button("🔄 Search again (clears screening and later steps)", key="lr_s_again"):
            lr.reset_from(out, "search")
            st.rerun()

    # ---- 3. screening --------------------------------------------------------------------
    step_header(3, "Title / abstract screening", done["screening"])
    if not done["screening"]:
        if st.button(f"Screen the {len(records)} records", key="lr_sc"):
            if run_step("Screening titles and abstracts", lambda log, live: lr.run_screening(out, log=log)):
                st.rerun()
        return
    rows = lr.load_screening(out)
    prisma = lr.load_prisma(out)
    m = st.columns(4)
    m[0].metric("Included", prisma.included)
    m[1].metric("Excluded", prisma.excluded)
    m[2].metric("Maybe — please check", prisma.maybe)
    changed = sum(r["decision"] != r["ai_decision"] for r in rows)
    m[3].metric("Changed by you", changed)
    st.markdown("**PRISMA flow** (counted by code)")
    st.graphviz_chart(prisma.flow_dot(), width="stretch")
    if prisma.exclusion_reasons:
        st.caption("Exclusion reasons: " + " · ".join(f"{r} ({n})" for r, n in prisma.exclusion_reasons.items()))
    with st.container():
        show = st.radio("Show", ["maybe", "include", "exclude", "all"], horizontal=True, key=f"lr_filter_{out.name}",
                        format_func=lambda x: {"maybe": "Maybe (check these)", "include": "Included",
                                               "exclude": "Excluded", "all": "All"}[x])
        view = [r for r in rows if show == "all" or r["decision"] == show]
        st.caption("Change the **Final decision** column to override the AI, then press Save.")
        edited = st.data_editor(
            pd.DataFrame(view, columns=lr.SCREENING_FIELDS),
            column_config={
                "paper_id": st.column_config.TextColumn("ID", disabled=True),
                "title": st.column_config.TextColumn("Title", disabled=True, width="medium"),
                "year": st.column_config.TextColumn("Year", disabled=True, width="small"),
                "ai_decision": st.column_config.TextColumn("AI decision", disabled=True),
                "decision": st.column_config.SelectboxColumn("Final decision", options=["include", "exclude", "maybe"],
                                                             required=True),
                "reason": st.column_config.TextColumn("Reason", width="large")},
            hide_index=True, num_rows="fixed", width="stretch", key=f"lr_scr_{out.name}_{show}_{ss.get('edit_v', 0)}")
        if st.button("💾 Save screening decisions", key="lr_sc_save"):
            by_id = {r["paper_id"]: r for r in edited.to_dict("records")}
            lr.save_screening(out, [{**r, **by_id.get(r["paper_id"], {})} for r in rows])
            ss.edit_v = ss.get("edit_v", 0) + 1  # fresh editors: old edits must not re-apply to other rows
            st.rerun()
    with st.expander("PRISMA flow as text"):
        st.markdown(prisma.flow_markdown())

    # ---- 4. evidence ---------------------------------------------------------------------
    stale = lr.evidence_out_of_date(out)
    step_header(4, "Evidence table", done["evidence"], stale)
    n_inc = prisma.included
    if not done["evidence"] or stale:
        if stale:
            st.warning("Your screening decisions changed after the evidence table was made. Update it "
                       "(only the newly included papers are sent to the AI; your edits are kept).")
        if n_inc == 0:
            st.info("No papers are included yet. Change some decisions to *include* above, or search again.")
            return
        if st.button(f"{'Update' if stale else 'Extract'} evidence from the {n_inc} included papers", key="lr_ex"):
            if run_step("Extracting evidence", lambda log, live: lr.run_extraction(out, log=log)):
                st.rerun()
        if not done["evidence"]:
            return
    ev = [r.model_dump() for r in lr.load_evidence(out)]
    st.caption("You can correct any cell, then press Save. The review is written from this table.")
    edited_ev = st.data_editor(
        pd.DataFrame(ev, columns=lr.EVIDENCE_FIELDS),
        column_config={"paper_id": st.column_config.TextColumn("ID", disabled=True)},
        hide_index=True, num_rows="fixed", width="stretch", key=f"lr_ev_{out.name}_{ss.get('edit_v', 0)}")
    if st.button("💾 Save evidence table", key="lr_ev_save"):
        by_id = {r["paper_id"]: r for r in edited_ev.fillna("").to_dict("records")}
        lr.save_evidence(out, [{**r, **by_id.get(r["paper_id"], {})} for r in ev])
        ss.edit_v = ss.get("edit_v", 0) + 1
        st.toast("Evidence table saved. Press “Re-write the review” to use your changes.")
        st.rerun()

    # ---- 5. review -----------------------------------------------------------------------
    step_header(5, "Literature review draft", done["review"])
    label = "Re-write the review from the current evidence table" if done["review"] else "Write the review"
    if st.button(label, key="lr_w", type="secondary" if done["review"] else "primary"):
        if run_step("Writing the review", lambda log, live: lr.run_writing(out, on_text=live), stream=True):
            st.rerun()
    if not done["review"]:
        return
    review = lr.load_review(out)
    ensure_docx(out / "review.md")
    papers = bridge.review_papers(out)
    (out / "references.bib").write_text(documents.papers_to_bibtex(papers), encoding="utf-8")
    (out / "references.ris").write_text(documents.papers_to_ris(papers), encoding="utf-8")

    st.markdown("#### 🔗 Next: write your paper")
    if st.button("✍️ Use these papers in the Writing Agent", type="primary", key="lr_bridge"):
        ss.aw_import_review, ss.aw_mode_next = str(out), "➕ New manuscript project"
        st.success("Done — open the **✍️ Academic Writing** tab. The reference list is filled in for you.")
    st.markdown("#### ⬇ Downloads")
    download_pair("Review", review, "literature_review", f"lr_dl_{out.name}")
    c = st.columns(4)
    c[0].download_button("Evidence table (CSV)", (out / "evidence.csv").read_bytes(), "evidence.csv", "text/csv",
                         width="stretch")
    c[1].download_button("Screening log (CSV)", (out / "screening.csv").read_bytes(), "screening.csv", "text/csv",
                         width="stretch")
    c[2].download_button("References (BibTeX)", (out / "references.bib").read_bytes(), "references.bib",
                         "application/x-bibtex", width="stretch")
    c[3].download_button("References (RIS)", (out / "references.ris").read_bytes(), "references.ris",
                         "application/x-research-info-systems", width="stretch")
    with st.container(border=True):
        st.markdown(review)


# =============================================================================== academic writing
def writing_tab() -> None:
    st.header("✍️ Academic Writing & Publication Agent")
    st.caption("“From Data to Manuscript” — manuscript, journal match, reviewer simulation, rebuttal")
    choice = mode_switch("aw_mode", ["➕ New manuscript project", "📂 Open a saved project"])
    if choice.startswith("➕"):
        new_project_form()
    else:
        projects = aw.list_projects(PROJECTS)
        if not projects:
            st.info("No saved projects yet — choose “New manuscript project”.")
        else:
            paths = [str(p) for p in projects]
            idx = paths.index(ss.aw_dir) if ss.get("aw_dir") in paths else 0
            sel = st.selectbox("Saved projects (newest first)", paths, index=idx,
                               format_func=lambda p: f"{aw.load_inputs(Path(p))['project']}  ·  {Path(p).name}")
            ss.aw_dir = sel
            render_project(Path(sel))
    st.divider()
    journal_catalogue_editor()


def new_project_form() -> None:
    st.button("📝 Load the example notes (wheat drought study from the original kit)",
              on_click=lambda: ss.update(aw_notes=SAMPLE_NOTES, aw_project="Example — drought wheat",
                                         aw_field="plant science"))
    reviews = bridge.usable_reviews(REVIEWS)
    review_opts = [""] + [str(p) for p in reviews]
    pre = ss.get("aw_import_review", "")
    with st.form("aw_new"):
        c1, c2, c3 = st.columns([2, 2, 1])
        project = c1.text_input("Project name", key="aw_project",
                                placeholder="e.g. Mammography + ultrasound AI for breast cancer")
        field = c2.text_input("Research field", key="aw_field", placeholder="e.g. breast surgery / oncology")
        reviewers = c3.slider("Reviewers", 1, 3, 3)
        what = st.radio("What do you have?", ["My notes and results — draft the manuscript for me",
                                              "A finished manuscript — review it and help me revise"], horizontal=True)
        notes = st.text_area("Notes and results (or paste your manuscript)", height=220, key="aw_notes",
                             placeholder="Aim, setting, patients/sample, methods, key results with numbers, "
                                         "limitations, references you want to cite …")
        upload = st.file_uploader("…or upload a file (Word, PDF, Markdown or text)", type=["docx", "pdf", "md", "txt"])
        st.markdown("**References the writer may cite**")
        src = st.selectbox("Import the included papers from one of my literature reviews", review_opts,
                           index=review_opts.index(pre) if pre in review_opts else 0,
                           format_func=lambda p: "— none —" if not p else bridge.review_label(Path(p)))
        use_bg = st.checkbox("Also give the review text to the writer (for the Introduction and Discussion)", value=True)
        refs = st.text_area("Other references (optional, one per line)", height=100)
        refs_up = st.file_uploader("…or upload a reference list", type=["docx", "pdf", "md", "txt", "bib", "ris"])
        how = st.radio("How should it run?", ["Step by step — I check each stage", "All 5 steps automatically"],
                       horizontal=True)
        if not st.form_submit_button("Create project", type="primary"):
            return
    text = notes.strip()
    if upload is not None:
        text = (text + "\n\n" if text else "") + documents.read_upload(upload.name, upload.getvalue()).strip()
    if len(text) < 50:
        st.error("Please add your notes/results or a manuscript (type, paste or upload).")
        return
    ref_text = refs.strip()
    if refs_up is not None:
        ref_text = (ref_text + "\n\n" if ref_text else "") + documents.read_upload(refs_up.name, refs_up.getvalue())
    background = ""
    if src:
        ref_text = (ref_text + "\n\n" if ref_text else "") + bridge.references_from_review(Path(src))
        background = bridge.background_from_review(Path(src)) if use_bg else ""
    mode = "manuscript" if what.startswith("A finished") else "notes"
    name = project.strip() or (upload.name.rsplit(".", 1)[0] if upload else text.splitlines()[0][:60])
    out = aw.new_project_dir(name, PROJECTS)
    aw.save_inputs(out, project=name, field=(field or "").strip() or "medicine", reviewers=reviewers, mode=mode,
                   notes=text if mode == "notes" else "", manuscript=text if mode == "manuscript" else "",
                   references=ref_text, background=background, source_review=src or None)
    ss.aw_dir, ss.aw_mode_next, ss.aw_autorun = str(out), "📂 Open a saved project", how.startswith("All")
    ss.pop("aw_import_review", None)
    st.rerun()


def reviews_markdown(reviews: ReviewSet) -> str:
    out = ["# Simulated peer review"]
    for r in reviews.reviews:
        out += [f"\n## {r.reviewer}", f"**Recommendation:** {r.recommendation}", "", r.summary, ""]
        out += [f"{c.number}. **[{c.severity}] {c.section}** — {c.comment}" for c in r.comments]
    return "\n".join(out) + "\n"


def render_project(out: Path) -> None:
    inp, done, stale = aw.load_inputs(out), aw.status(out), aw.out_of_date(out)
    st.subheader(inp["project"])
    st.caption(f"Field: {inp['field']} · {inp['reviewers']} reviewer(s) · "
               + ("drafting from notes" if inp["mode"] == "notes" else "reviewing an existing manuscript")
               + (" · references imported from a literature review" if inp.get("source_review") else ""))
    progress_line(["Manuscript", "Journals", "Peer review", "Response letter", "Revision"],
                  [done[s] and not stale.get(s, False) for s in aw.STAGES])

    with st.expander("📄 Inputs — notes and references (click to view or edit)"):
        with st.form("aw_edit_inputs"):
            notes = st.text_area("Notes and results", inp["notes"], height=200, disabled=inp["mode"] == "manuscript",
                                 help="In “existing manuscript” mode, edit the manuscript in Step 1 instead.")
            refs = st.text_area("References", inp["references"], height=150)
            c1, c2 = st.columns(2)
            field = c1.text_input("Research field", inp["field"])
            reviewers = c2.slider("Reviewers", 1, 3, int(inp["reviewers"]))
            if st.form_submit_button("Save inputs"):
                aw.save_inputs(out, project=inp["project"], field=field, reviewers=reviewers, mode=inp["mode"],
                               notes=notes, manuscript=aw.load_manuscript(out) if inp["mode"] == "manuscript" else "",
                               references=refs, background=inp["background"], source_review=inp.get("source_review"))
                st.success("Saved. Re-draft the manuscript (Step 1) to use the new notes.")

    def run_all(log, live):
        aw.run_remaining(out, log=log, on_text_for=lambda stage: live.reset())

    pending = any(not done[s] or stale.get(s, False) for s in aw.STAGES)
    if ss.pop("aw_autorun", False) or st.button("▶ Run all remaining steps", type="primary", disabled=not pending,
                                                key="aw_all"):
        if run_step("Running the writing pipeline", run_all, stream=True):
            st.rerun()
    st.divider()

    # ---- 1. manuscript -------------------------------------------------------------------
    step_header(1, "Manuscript", done["manuscript"])
    if inp["mode"] == "notes":
        label = "Re-draft the manuscript from my notes" if done["manuscript"] else "Draft the manuscript"
        if st.button(label, key="aw_m", type="secondary" if done["manuscript"] else "primary"):
            if run_step("Drafting the manuscript", lambda log, live: aw.run_manuscript(out, on_text=live), stream=True):
                st.rerun()
    if not done["manuscript"]:
        return
    ms = aw.load_manuscript(out)
    ensure_docx(out / aw.FILES["manuscript"])
    read_tab, edit_tab = st.tabs(["📖 Read", "✏️ Edit"])
    with read_tab:
        download_pair("Manuscript v1", ms, "manuscript_v1", f"aw_dl_v1_{out.name}")
        with st.container(border=True, height=600):
            st.markdown(ms)
    with edit_tab:
        with st.form("aw_edit_ms"):
            new_ms = st.text_area("Manuscript (Markdown)", ms, height=500)
            if st.form_submit_button("💾 Save manuscript"):
                aw.save_manuscript(out, new_ms)
                st.rerun()
        st.caption("After saving, steps 2–5 are marked ⚠️ out of date — re-run them to use your edits.")

    # ---- 2. journals ---------------------------------------------------------------------
    step_header(2, "Journal matching", done["journals"], stale["journals"])
    if st.button("Re-run journal matching" if done["journals"] else "Find the best journals", key="aw_j"):
        if run_step("Matching journals", lambda log, live: aw.run_journal_matching(out)):
            st.rerun()
    if done["journals"]:
        rk = aw.load_ranking(out)
        st.markdown(f"*{rk.manuscript_summary}*")
        st.dataframe(pd.DataFrame([{"Journal": m.journal, "Scope fit (1–10)": m.scope_fit, "Impact": m.impact_band,
                                    "Open access": m.open_access,
                                    "APC (USD)": f"${m.estimated_apc_usd:,}" if m.estimated_apc_usd else "not known",
                                    "Acceptance": m.acceptance_probability} for m in rk.matches]),
                     hide_index=True, width="stretch")
        for m in rk.matches:
            with st.expander(f"{m.journal} — why, and tips"):
                st.markdown(f"**Why:** {m.reason}\n\n**Tips for this journal:** {m.tips_for_this_journal}")
        if rk.avoid:
            st.markdown("**Poor fit:**\n" + "\n".join(f"- {a}" for a in rk.avoid))
        st.caption("Impact, fees and acceptance odds are indicative. Check the journal's website before submitting.")

    # ---- 3. reviews ----------------------------------------------------------------------
    step_header(3, "Simulated peer review", done["reviews"], stale["reviews"])
    if st.button("Re-run peer review" if done["reviews"] else f"Simulate peer review ({inp['reviewers']} reviewers)",
                 key="aw_r"):
        if run_step("Simulating peer review", lambda log, live: aw.run_reviews(out)):
            st.rerun()
    if not done["reviews"]:
        return
    rv = aw.load_reviews(out)
    for r in rv.reviews:
        with st.expander(f"{r.reviewer} — recommends **{r.recommendation}** ({len(r.comments)} comments)"):
            st.markdown(r.summary)
            st.dataframe(pd.DataFrame([c.model_dump() for c in r.comments]), hide_index=True, width="stretch",
                         column_config={"comment": st.column_config.TextColumn("comment", width="large")})
    rv_md = reviews_markdown(rv)
    download_pair("Peer reviews", rv_md, "simulated_peer_review", f"aw_dl_rv_{out.name}")

    # ---- 4. response letter --------------------------------------------------------------
    step_header(4, "Response letter", done["letter"], stale["letter"])
    if st.button("Re-write the response letter" if done["letter"] else "Write the response letter", key="aw_l"):
        if run_step("Writing the response letter", lambda log, live: aw.run_letter(out, on_text=live), stream=True):
            st.rerun()
    if done["letter"]:
        letter = aw.read_output(out, "letter")
        ensure_docx(out / aw.FILES["letter"])
        download_pair("Response letter", letter, "response_letter", f"aw_dl_l_{out.name}")
        with st.expander("Read the response letter"):
            st.markdown(letter)

    # ---- 5. revision ---------------------------------------------------------------------
    step_header(5, "Revised manuscript (changes in bold)", done["revision"], stale["revision"])
    if st.button("Re-write the revised manuscript" if done["revision"] else "Write the revised manuscript", key="aw_v"):
        if run_step("Revising the manuscript", lambda log, live: aw.run_revision(out, on_text=live), stream=True):
            st.rerun()
    if done["revision"]:
        v2 = aw.read_output(out, "revision")
        ensure_docx(out / aw.FILES["revision"])
        download_pair("Revised manuscript v2", v2, "manuscript_v2", f"aw_dl_v2_{out.name}")
        with st.expander("Read the revised manuscript"):
            st.markdown(v2)


def journal_catalogue_editor() -> None:
    with st.expander(f"📚 Journal catalogue used for matching ({len(jr.load_catalogue())} journals) — view, edit, "
                     "or refresh live data"):
        st.caption("The matching agent may only recommend journals from this list. Add the journals you are "
                   "considering (one row each) and press Save. Fees and impact bands are indicative.")
        cat = pd.DataFrame([j.model_dump() for j in jr.load_catalogue()])
        cat["fields"] = cat["fields"].apply(lambda v: ", ".join(v))
        if HOSTED:
            st.caption("Online, the catalogue is read-only (it is shared by everyone). Edit it in the copy on your "
                       "own computer, or in `academic_writing/journals.py` on GitHub.")
        edited = st.data_editor(cat, num_rows="dynamic", hide_index=True, width="stretch", disabled=HOSTED,
                                key=f"jr_cat_{ss.get('edit_v', 0)}",
                                column_config={"impact_band": st.column_config.SelectboxColumn(
                                    options=["very high", "high", "medium", "emerging"]),
                                    "open_access": st.column_config.SelectboxColumn(
                                    options=["gold", "hybrid", "subscription", "diamond"])})
        c1, c2, c3 = st.columns(3)
        if c1.button("💾 Save catalogue", width="stretch", disabled=HOSTED):
            def txt(v) -> str:
                return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()

            def num(v) -> int | None:
                return None if txt(v) == "" else int(float(v))

            try:
                rows = [jr.Journal(name=txt(r.get("name")), publisher=txt(r.get("publisher")),
                                   scope=txt(r.get("scope")),
                                   fields=[x.strip() for x in txt(r.get("fields")).split(",") if x.strip()],
                                   impact_band=txt(r.get("impact_band")) or "medium",
                                   open_access=txt(r.get("open_access")) or "hybrid",
                                   apc_usd=num(r.get("apc_usd")), review_weeks=num(r.get("review_weeks")),
                                   acceptance_rate=txt(r.get("acceptance_rate")) or "unknown")
                        for r in edited.to_dict("records") if txt(r.get("name"))]
                jr.save_catalogue(rows)
                ss.edit_v = ss.get("edit_v", 0) + 1
                st.toast(f"Saved {len(rows)} journals.")
                st.rerun()
            except ValueError as exc:
                st.error(f"Could not save — please check the numbers: {exc}")
        if c2.button("↩️ Reset to the built-in list", width="stretch", disabled=HOSTED):
            jr.reset_catalogue()
            ss.edit_v = ss.get("edit_v", 0) + 1
            st.rerun()
        if c3.button("🌐 Refresh live data from OpenAlex", width="stretch"):
            run_step("Fetching live journal data from OpenAlex",
                     lambda log, live: jr.refresh_live_data(log=log), needs_key=False)
        live = jr.load_live()
        if live:
            st.markdown("**Live data from OpenAlex** (used by the matching agent when available)")
            st.dataframe(pd.DataFrame([{"journal": k, "publisher": v.get("publisher"), "open access": v.get("is_oa"),
                                        "in DOAJ": v.get("is_in_doaj"), "APC (USD)": v.get("apc_usd"),
                                        "2-yr mean citedness": v.get("two_year_mean_citedness"),
                                        "h-index": v.get("h_index"), "fetched": v.get("fetched")}
                                       for k, v in live.items()]), hide_index=True, width="stretch")
            st.caption("“2-year mean citedness” is OpenAlex's open equivalent of an impact factor (not identical). "
                       "It reads low for journals that publish many meeting abstracts (e.g. British Journal of "
                       "Surgery), so the matching agent uses only the fee and open-access columns.")


# =============================================================================== files
def files_tab() -> None:
    st.header("📁 My files")
    if HOSTED:
        st.warning("Online storage is temporary: download a ZIP of anything you want to keep.")
    else:
        st.caption(f"Everything is saved in {OUTPUTS}")
        if st.button("📂 Open the Outputs folder", key="files_open"):
            open_folder(OUTPUTS)
    for title, items, label in (
            ("📚 Literature reviews", lr.list_reviews(REVIEWS), lambda d: lr.load_settings(d)["question"]),
            ("✍️ Manuscript projects", aw.list_projects(PROJECTS), lambda d: aw.load_inputs(d)["project"])):
        st.subheader(title)
        if not items:
            st.caption("Nothing yet.")
        for d in items:
            files = sorted(f.name for f in d.iterdir() if f.is_file())
            with st.expander(f"{label(d)}  ·  {time.strftime('%d %b %Y %H:%M', time.localtime(d.stat().st_mtime))}"):
                st.markdown(" · ".join(f"`{f}`" for f in files))
                c1, c2 = st.columns(2)
                c1.download_button("⬇ Download everything (ZIP)", zip_folder(d), f"{d.name}.zip", "application/zip",
                                   key=f"zip_{d}", width="stretch")
                if not HOSTED and c2.button("📂 Open this folder", key=f"open_{d}", width="stretch"):
                    open_folder(d)


# =============================================================================== main
password_gate()
llm.use_session(api_key=ss.get("user_api_key"), model=ss.get("user_model"), bulk_model=ss.get("user_bulk_model"))
sidebar()
tabs = st.tabs(["🏠 Start here", "📚 Literature Review", "✍️ Academic Writing", "📁 My files"])
with tabs[0]:
    home_tab()
with tabs[1]:
    literature_tab()
with tabs[2]:
    writing_tab()
with tabs[3]:
    files_tab()
