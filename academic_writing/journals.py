"""
journals.py — an editable journal knowledge base for the Journal Matching Agent.

    JOURNALS          built-in catalogue (the original kit's 15 journals + breast cancer, surgery,
                      oncology, radiology and digital-health journals)
    journal_catalogue.json   your edited catalogue, if you saved one from the web app (wins over the built-in list)
    journals_live.json       live metrics fetched from OpenAlex (free, no key): publisher, open-access
                             status, DOAJ listing, APC in USD, 2-year mean citedness, h-index

Impact bands, review times and acceptance rates in the built-in list are indicative only. Where a
value was not known it is left empty rather than guessed — refresh from OpenAlex and always check
the journal's own website before submitting.

Adapted from the Codanics "Top five AI agents for research" kit (agent 04).
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Callable

import requests
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
CUSTOM_FILE = HERE / "journal_catalogue.json"
LIVE_FILE = HERE / "journals_live.json"


class Journal(BaseModel):
    name: str
    publisher: str
    scope: str
    fields: list[str]
    impact_band: str                  # "very high" | "high" | "medium" | "emerging"
    open_access: str                  # "gold" | "hybrid" | "subscription" | "diamond"
    apc_usd: int | None = None        # article processing charge if OA (None = not known, check website)
    review_weeks: int | None = None   # typical first-decision time (None = not known)
    acceptance_rate: str = "unknown"  # rough band


def _j(name, publisher, scope, fields, impact, oa, apc=None, weeks=None, acc="unknown") -> Journal:
    return Journal(name=name, publisher=publisher, scope=scope, fields=fields, impact_band=impact,
                   open_access=oa, apc_usd=apc, review_weeks=weeks, acceptance_rate=acc)


JOURNALS: list[Journal] = [
    # ---- original kit catalogue -------------------------------------------------------------
    _j("Computers and Electronics in Agriculture", "Elsevier",
       "Computing, sensing and AI applied to agriculture and food production",
       ["agriculture", "plant science", "AI", "remote sensing"], "high", "hybrid", 3500, 8, "~25%"),
    _j("Plant Phenomics", "Science Partner Journals / AAAS",
       "High-throughput plant phenotyping, imaging, sensors and analytics",
       ["plant science", "phenotyping", "AI"], "high", "gold", 3000, 6, "~30%"),
    _j("Frontiers in Plant Science", "Frontiers",
       "All areas of plant biology including stress physiology and computational approaches",
       ["plant science", "biology", "stress"], "medium", "gold", 3300, 8, "~50%"),
    _j("Remote Sensing", "MDPI",
       "Remote-sensing science and applications including UAV and hyperspectral imaging",
       ["remote sensing", "agriculture", "AI"], "medium", "gold", 2700, 4, "~45%"),
    _j("Scientific Reports", "Springer Nature",
       "Multidisciplinary, technically sound research in natural sciences",
       ["multidisciplinary", "biology", "AI", "medicine"], "medium", "gold", 2690, 10, "~45%"),
    _j("Nature Machine Intelligence", "Springer Nature",
       "High-impact AI/ML research with broad scientific significance",
       ["AI", "machine learning", "multidisciplinary"], "very high", "hybrid", 12000, 12, "<10%"),
    _j("Bioinformatics", "Oxford University Press",
       "Computational methods and tools for biological data analysis",
       ["bioinformatics", "genomics", "biology"], "high", "hybrid", 3500, 8, "~20%"),
    _j("BMC Bioinformatics", "Springer Nature",
       "Bioinformatics methods, databases and applications",
       ["bioinformatics", "genomics"], "medium", "gold", 2790, 10, "~35%"),
    _j("Theoretical and Applied Genetics", "Springer",
       "Plant genetics, genomics and breeding",
       ["genetics", "plant science", "breeding"], "high", "hybrid", 3690, 8, "~25%"),
    _j("Journal of Medical Internet Research", "JMIR Publications",
       "Digital health, AI in medicine, eHealth",
       ["medicine", "digital health", "AI"], "high", "gold", 3300, 6, "~25%"),
    _j("IEEE Access", "IEEE",
       "Multidisciplinary engineering and computer science, rapid publication",
       ["engineering", "computer science", "AI"], "medium", "gold", 1995, 4, "~30%"),
    _j("PLOS ONE", "PLOS",
       "Multidisciplinary; rigorous methodology rather than perceived impact",
       ["multidisciplinary", "biology", "medicine", "social science"], "medium", "gold", 2290, 10, "~45%"),
    _j("Expert Systems with Applications", "Elsevier",
       "Applied AI and intelligent systems across domains",
       ["AI", "computer science", "applications"], "high", "hybrid", 3600, 10, "~20%"),
    _j("Agricultural Water Management", "Elsevier",
       "Water use, irrigation, drought and crop-water relations",
       ["agriculture", "water", "drought"], "high", "hybrid", 3500, 8, "~25%"),
    _j("Heliyon", "Cell Press / Elsevier",
       "Multidisciplinary open-access journal for technically sound research",
       ["multidisciplinary"], "emerging", "gold", 2000, 6, "~50%"),
    # ---- breast cancer -------------------------------------------------------------------------
    _j("Breast Cancer Research", "BMC / Springer Nature",
       "Breast cancer biology, translational research, imaging biomarkers and clinical studies",
       ["breast cancer", "oncology", "medicine"], "high", "gold"),
    _j("npj Breast Cancer", "Nature Portfolio",
       "Breast cancer research across basic, translational and clinical science",
       ["breast cancer", "oncology", "medicine"], "high", "gold"),
    _j("The Breast", "Elsevier",
       "Clinical breast cancer: diagnosis, surgery, oncology, screening and survivorship",
       ["breast cancer", "breast surgery", "oncology", "medicine"], "high", "gold"),
    _j("Breast Cancer Research and Treatment", "Springer",
       "Clinical and laboratory research on breast cancer treatment and outcomes",
       ["breast cancer", "oncology", "medicine"], "medium", "hybrid"),
    _j("Clinical Breast Cancer", "Elsevier",
       "Clinical research on detection, diagnosis and treatment of breast cancer",
       ["breast cancer", "oncology", "medicine"], "medium", "hybrid"),
    _j("Journal of Breast Imaging", "Oxford University Press / Society of Breast Imaging",
       "Breast imaging: mammography, ultrasound, MRI, intervention and AI in breast imaging",
       ["breast imaging", "radiology", "breast cancer"], "emerging", "hybrid"),
    # ---- surgery / surgical oncology ------------------------------------------------------------
    _j("British Journal of Surgery", "Oxford University Press",
       "General and specialist surgery including surgical oncology and breast surgery",
       ["surgery", "breast surgery", "medicine"], "very high", "hybrid"),
    _j("Annals of Surgical Oncology", "Springer",
       "Surgical oncology including breast cancer surgery and multidisciplinary care",
       ["surgical oncology", "breast surgery", "oncology"], "high", "hybrid"),
    _j("European Journal of Surgical Oncology", "Elsevier",
       "Surgical oncology research, including breast, with a European focus",
       ["surgical oncology", "breast surgery", "oncology"], "medium", "hybrid"),
    # ---- radiology / imaging AI ------------------------------------------------------------------
    _j("Radiology", "Radiological Society of North America",
       "Clinical radiology research across all imaging modalities",
       ["radiology", "medical imaging", "medicine"], "very high", "hybrid"),
    _j("Radiology: Artificial Intelligence", "Radiological Society of North America",
       "AI and machine learning applied to medical imaging",
       ["radiology", "AI", "medical imaging", "deep learning"], "high", "hybrid"),
    _j("European Radiology", "Springer",
       "Clinical radiology across modalities, including breast imaging and imaging AI",
       ["radiology", "medical imaging", "breast imaging"], "high", "hybrid"),
    _j("Insights into Imaging", "Springer",
       "Radiology education, practice, imaging research and AI",
       ["radiology", "medical imaging"], "medium", "gold"),
    _j("European Journal of Radiology", "Elsevier",
       "Clinical radiology research across modalities",
       ["radiology", "medical imaging"], "medium", "hybrid"),
    _j("Diagnostics", "MDPI",
       "Diagnostic medicine including imaging, pathology and AI-based diagnosis",
       ["diagnostics", "medical imaging", "AI", "medicine"], "emerging", "gold"),
    # ---- oncology / general medicine / digital health ---------------------------------------
    _j("BMC Cancer", "BMC / Springer Nature",
       "All aspects of cancer research including clinical and epidemiological studies",
       ["oncology", "cancer", "medicine"], "medium", "gold"),
    _j("Cancers", "MDPI",
       "Oncology across basic, translational and clinical research",
       ["oncology", "cancer", "medicine"], "medium", "gold"),
    _j("Frontiers in Oncology", "Frontiers",
       "Oncology research across clinical, translational and computational topics",
       ["oncology", "cancer", "medicine", "AI"], "medium", "gold"),
    _j("JAMA Network Open", "American Medical Association",
       "Clinical research across all medical specialties, including oncology and surgery",
       ["medicine", "oncology", "surgery"], "high", "gold"),
    _j("npj Digital Medicine", "Nature Portfolio",
       "Digital health and AI in clinical medicine",
       ["digital health", "AI", "medicine"], "very high", "gold"),
    _j("The Lancet Digital Health", "Elsevier / The Lancet",
       "Digital technologies and AI in health care",
       ["digital health", "AI", "medicine"], "very high", "gold"),
    _j("Malaysian Journal of Medical Sciences", "Penerbit Universiti Sains Malaysia",
       "Medical and health sciences research, with a focus on Malaysia and the region",
       ["medicine", "surgery", "health sciences"], "emerging", "gold"),
]


# -------------------------------------------------------------------- catalogue files
def load_catalogue() -> list[Journal]:
    """Your saved catalogue if there is one, otherwise the built-in list."""
    if CUSTOM_FILE.exists():
        return [Journal(**j) for j in json.loads(CUSTOM_FILE.read_text(encoding="utf-8"))]
    return list(JOURNALS)


def save_catalogue(journals: list[Journal]) -> None:
    CUSTOM_FILE.write_text(json.dumps([j.model_dump() for j in journals], indent=2, ensure_ascii=False),
                           encoding="utf-8")


def reset_catalogue() -> None:
    CUSTOM_FILE.unlink(missing_ok=True)


def load_live() -> dict[str, dict]:
    if LIVE_FILE.exists():
        return json.loads(LIVE_FILE.read_text(encoding="utf-8"))
    return {}


# ------------------------------------------------------------------- OpenAlex (live)
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


def fetch_openalex(name: str, timeout: int = 20) -> dict | None:
    """Look a journal up in OpenAlex (https://openalex.org) and return a few verifiable metrics."""
    resp = requests.get("https://api.openalex.org/sources", timeout=timeout,
                        params={"search": name, "per-page": 10},
                        headers={"User-Agent": "ai-agent-for-academic/1.0"})
    resp.raise_for_status()
    results = [r for r in resp.json().get("results", []) if r.get("type") == "journal"]
    exact = [r for r in results if _norm(r.get("display_name", "")) == _norm(name)]
    if not exact:
        exact = [r for r in results if _norm(name) in [_norm(a) for a in r.get("alternate_titles") or []]]
    if not exact:
        return None
    r = max(exact, key=lambda x: x.get("works_count") or 0)
    stats = r.get("summary_stats") or {}
    return {
        "openalex_name": r.get("display_name"),
        "publisher": r.get("host_organization_name"),
        "issn_l": r.get("issn_l"),
        "is_oa": r.get("is_oa"),
        "is_in_doaj": r.get("is_in_doaj"),
        "apc_usd": r.get("apc_usd"),
        "two_year_mean_citedness": round(stats["2yr_mean_citedness"], 2)
        if stats.get("2yr_mean_citedness") is not None else None,
        "h_index": stats.get("h_index"),
        "works_count": r.get("works_count"),
        "homepage_url": r.get("homepage_url"),
        "openalex_id": r.get("id"),
        "fetched": date.today().isoformat(),
    }


def refresh_live_data(journals: list[Journal] | None = None, log: Callable[[str], None] = print) -> dict:
    journals = journals or load_catalogue()
    live = load_live()
    for j in journals:
        try:
            info = fetch_openalex(j.name)
        except Exception as exc:  # network errors must never break the app
            log(f"{j.name}: FAILED ({type(exc).__name__})")
            continue
        if info:
            live[j.name] = info
            log(f"{j.name}: ok")
        else:
            log(f"{j.name}: not found in OpenAlex")
    LIVE_FILE.write_text(json.dumps(live, indent=2, ensure_ascii=False), encoding="utf-8")
    return live


def catalogue_text() -> str:
    """The catalogue as JSON lines for the model, with live OpenAlex metrics attached where known."""
    live = load_live()
    lines = []
    for j in load_catalogue():
        d = j.model_dump()
        if j.name in live:
            # Only cost/access facts go to the model. OpenAlex's citation averages are left out on
            # purpose: journals that publish many meeting abstracts (e.g. British Journal of Surgery)
            # get artificially low averages, which would mislead the ranking.
            d["live_openalex"] = {k: v for k, v in live[j.name].items()
                                  if k in ("is_oa", "is_in_doaj", "apc_usd", "fetched")}
        lines.append(json.dumps(d, ensure_ascii=False))
    return "\n".join(lines)
