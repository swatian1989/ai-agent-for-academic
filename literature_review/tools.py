"""
tools.py — real literature-search tools for the Literature Review Agent.

Every function returns a list[Paper] in ONE common shape, no matter which database it came from.
All four sources are free, public APIs (no key needed; keys only raise rate limits):

    arXiv            https://arxiv.org/help/api
    Semantic Scholar https://api.semanticscholar.org/
    PubMed           https://www.ncbi.nlm.nih.gov/books/NBK25501/  (E-utilities)
    Crossref         https://api.crossref.org/

Golden rule of this project: the LLM may only cite papers that came out of these tools.

Adapted from the Codanics "Top five AI agents for research" kit (agent 02).
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

USER_AGENT = "ai-agent-for-academic/1.0 (systematic review assistant)"
TIMEOUT = 30


class Paper(BaseModel):
    """One normalised bibliographic record."""
    id: str = Field(description="Stable identifier, e.g. arxiv:2401.01234, pmid:38012345, doi:10.1000/xyz")
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    citations: int | None = None
    url: str = ""
    source: str = ""

    def short(self, n_abstract: int = 900) -> str:
        """Compact text block given to the LLM (keeps prompts small and citable)."""
        auth = ", ".join(self.authors[:3]) + (" et al." if len(self.authors) > 3 else "")
        cites = f" | citations: {self.citations}" if self.citations is not None else ""
        abstract = (self.abstract or "")[:n_abstract]
        return f"[{self.id}] {self.title} ({self.year}) — {auth} | {self.venue}{cites}\n{abstract}\n"


# ----------------------------------------------------------------------------- arXiv
def search_arxiv(query: str, max_results: int = 25) -> list[Paper]:
    import arxiv  # pip install arxiv

    client = arxiv.Client(page_size=min(max_results, 100), delay_seconds=3, num_retries=3)
    search = arxiv.Search(query=query, max_results=max_results,
                          sort_by=arxiv.SortCriterion.Relevance)
    papers: list[Paper] = []
    for r in client.results(search):
        papers.append(Paper(
            id=f"arxiv:{r.get_short_id()}",
            title=" ".join(r.title.split()),
            abstract=" ".join(r.summary.split()),
            authors=[a.name for a in r.authors],
            year=r.published.year if r.published else None,
            venue=(r.journal_ref or "arXiv"),
            url=r.entry_id,
            source="arxiv",
        ))
    return papers


# ------------------------------------------------------------------- Semantic Scholar
def search_semantic_scholar(query: str, max_results: int = 25, year_from: int | None = None) -> list[Paper]:
    headers = {"User-Agent": USER_AGENT}
    key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if key:
        headers["x-api-key"] = key
    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": "title,abstract,year,authors,citationCount,externalIds,venue,url",
    }
    if year_from:
        params["year"] = f"{year_from}-"
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    for attempt in range(4):  # anonymous access is heavily rate-limited: back off on 429
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 429:
            break
        time.sleep(5 * (attempt + 1))
    resp.raise_for_status()
    papers: list[Paper] = []
    for d in resp.json().get("data", []):
        ext = d.get("externalIds") or {}
        if ext.get("DOI"):
            pid = f"doi:{ext['DOI']}"
        elif ext.get("ArXiv"):
            pid = f"arxiv:{ext['ArXiv']}"
        elif ext.get("PubMed"):
            pid = f"pmid:{ext['PubMed']}"
        else:
            pid = f"s2:{d.get('paperId')}"
        papers.append(Paper(
            id=pid,
            title=d.get("title") or "",
            abstract=d.get("abstract") or "",
            authors=[a.get("name", "") for a in d.get("authors") or []],
            year=d.get("year"),
            venue=d.get("venue") or "",
            citations=d.get("citationCount"),
            url=d.get("url") or "",
            source="semantic_scholar",
        ))
    return papers


# --------------------------------------------------------------------------- PubMed
def search_pubmed(query: str, max_results: int = 25) -> list[Paper]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    common = {"tool": "ai-agent-for-academic", "email": os.getenv("NCBI_EMAIL", "")}
    if os.getenv("NCBI_API_KEY"):
        common["api_key"] = os.getenv("NCBI_API_KEY")

    ids = requests.get(f"{base}/esearch.fcgi", timeout=TIMEOUT, params={
        **common, "db": "pubmed", "term": query, "retmax": max_results, "retmode": "json",
        "sort": "relevance"}).json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    xml = requests.get(f"{base}/efetch.fcgi", timeout=TIMEOUT, params={
        **common, "db": "pubmed", "id": ",".join(ids), "retmode": "xml"}).text
    root = ET.fromstring(xml)
    papers: list[Paper] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = " ".join((art.findtext(".//ArticleTitle") or "").split())
        abstract = " ".join(" ".join(t.itertext()) for t in art.findall(".//AbstractText")).strip()
        authors = []
        for a in art.findall(".//Author"):
            last, fore = a.findtext("LastName"), a.findtext("ForeName")
            if last:
                authors.append(f"{fore} {last}".strip())
        year = art.findtext(".//PubDate/Year") or art.findtext(".//ArticleDate/Year")
        venue = art.findtext(".//Journal/Title") or ""
        doi = None
        for el in art.findall(".//ArticleId"):
            if el.get("IdType") == "doi":
                doi = el.text
        papers.append(Paper(
            id=f"pmid:{pmid}", title=title, abstract=abstract, authors=authors,
            year=int(year) if year and year.isdigit() else None, venue=venue,
            url=f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            source="pubmed"))
    return papers


# ------------------------------------------------------------------------- Crossref
def search_crossref(query: str, max_results: int = 25) -> list[Paper]:
    resp = requests.get("https://api.crossref.org/works", timeout=TIMEOUT,
                        headers={"User-Agent": USER_AGENT},
                        params={"query": query, "rows": min(max_results, 100),
                                "filter": "type:journal-article",
                                "select": "DOI,title,abstract,author,issued,container-title,is-referenced-by-count,URL"})
    resp.raise_for_status()
    papers: list[Paper] = []
    for it in resp.json().get("message", {}).get("items", []):
        title = " ".join((it.get("title") or [""])[0].split())
        if not title:
            continue
        abstract = re.sub(r"<[^>]+>", " ", it.get("abstract") or "")
        abstract = " ".join(abstract.split())
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in it.get("author") or []]
        parts = (it.get("issued") or {}).get("date-parts") or [[None]]
        year = parts[0][0] if parts and parts[0] else None
        papers.append(Paper(
            id=f"doi:{it.get('DOI')}", title=title, abstract=abstract, authors=authors,
            year=year, venue=(it.get("container-title") or [""])[0],
            citations=it.get("is-referenced-by-count"), url=it.get("URL") or "", source="crossref"))
    return papers


# ---------------------------------------------------------------------- utilities
def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())[:80]


def dedupe(papers: Iterable[Paper]) -> list[Paper]:
    """Merge duplicates across databases (same DOI or same normalised title)."""
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        nt = _norm_title(p.title)
        if p.id in seen_ids or (nt and nt in seen_titles):
            continue
        seen_ids.add(p.id)
        if nt:
            seen_titles.add(nt)
        out.append(p)
    return out


SOURCES = {
    "arxiv": search_arxiv,
    "semantic_scholar": search_semantic_scholar,
    "pubmed": search_pubmed,
    "crossref": search_crossref,
}


def search_all(query: str, max_per_source: int = 20,
               sources: Iterable[str] = ("arxiv", "semantic_scholar", "pubmed", "crossref"),
               log=print, dedup: bool = True) -> list[Paper]:
    """Query every requested source, tolerate failures, and return a de-duplicated list.
    With dedup=False every retrieved record is returned, so PRISMA can count duplicates honestly."""
    found: list[Paper] = []
    for name in sources:
        fn = SOURCES[name]
        try:
            res = fn(query, max_per_source)
            log(f"  {name:<17} {len(res):>3} records")
            found.extend(res)
        except Exception as exc:  # network / rate limit / parse errors must never kill the run
            log(f"  {name:<17} FAILED ({type(exc).__name__}: {exc})")
    if not dedup:
        return found
    papers = dedupe(found)
    log(f"  total after dedupe {len(papers):>3}")
    return papers


# -------------------------------------------------------------------- offline demo
OFFLINE_SAMPLE: list[Paper] = [
    Paper(id="demo:1", title="Deep learning for drought stress detection in wheat using RGB imagery",
          abstract="A CNN trained on RGB canopy images classifies drought stress in wheat with 92% accuracy under field conditions. Hyperspectral and genomic data were not used.",
          authors=["A. Khan", "B. Ali"], year=2023, venue="Computers and Electronics in Agriculture", citations=41, source="demo"),
    Paper(id="demo:2", title="Hyperspectral indices for early drought detection in cereals: a review",
          abstract="Reviews vegetation indices derived from hyperspectral sensors for early drought detection; highlights the lack of integration with machine learning and genotype information.",
          authors=["C. Zhang"], year=2022, venue="Remote Sensing", citations=88, source="demo"),
    Paper(id="demo:3", title="Genomic prediction of drought tolerance in wheat landraces",
          abstract="GBLUP and random forest models predict drought tolerance from SNP data across 400 landraces; phenotypic imaging data were unavailable.",
          authors=["D. Rehman", "E. Fatima"], year=2024, venue="Theoretical and Applied Genetics", citations=12, source="demo"),
    Paper(id="demo:4", title="Explainable machine learning for crop stress phenotyping",
          abstract="Applies SHAP to gradient boosting models of crop stress from multispectral UAV data; calls for multimodal fusion with genomic markers.",
          authors=["F. Ahmed"], year=2024, venue="Plant Phenomics", citations=9, source="demo"),
    Paper(id="demo:5", title="Transformer models for time-series prediction of soil moisture and crop water stress",
          abstract="A temporal transformer predicts soil moisture and canopy temperature from weather and satellite data, outperforming LSTM baselines; not validated on wheat genotypes.",
          authors=["G. Li", "H. Wang"], year=2023, venue="Agricultural Water Management", citations=27, source="demo"),
    Paper(id="demo:6", title="Multimodal data fusion in precision agriculture: challenges and opportunities",
          abstract="Surveys fusion of imaging, sensor, weather and omics data; identifies the absence of open benchmark datasets combining phenomics and genomics for drought.",
          authors=["I. Hussain"], year=2025, venue="Frontiers in Plant Science", citations=5, source="demo"),
]
