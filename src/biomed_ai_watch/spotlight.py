"""Weekly Topic Spotlight: expand a topic into search terms, measure its publication trend,
research recent developments on the web, and chart what's found."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path

from . import llm
from .sources.papers import EUTILS, _ncbi_params
from .http import session

log = logging.getLogger(__name__)

AI_CLAUSE = ('("artificial intelligence"[tiab] OR "machine learning"[tiab] OR "deep learning"[tiab] '
             'OR "large language model*"[tiab] OR "natural language processing"[tiab] OR "Artificial Intelligence"[mh])')


def pick_topic(cfg: dict, end: date, override: str | None = None) -> str:
    if override:
        return override
    topics = cfg["spotlight"]["topics"]
    return topics[end.isocalendar()[1] % len(topics)]


# ---------- 1. synonyms and search terms ----------

TERMS_SCHEMA = {
    "type": "object",
    "properties": {
        "synonyms": {"type": "array", "items": {"type": "string"},
                     "description": "Alternate names, abbreviations, and closely related terms"},
        "mesh_terms": {"type": "array", "items": {"type": "string"}, "description": "Relevant MeSH headings"},
        "pubmed_query": {"type": "string",
                         "description": "PubMed query for the topic alone (no AI terms), using [tiab] and [mh] tags"},
        "web_queries": {"type": "array", "items": {"type": "string"},
                        "description": "4-8 web search queries for recent AI developments in this topic"},
        "subtopics": {
            "type": "array",
            "description": "6-8 distinct clinical or technical subareas of the topic, for a research gap map",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Short label, max 30 characters"},
                               "pubmed_clause": {"type": "string",
                                                 "description": "PubMed clause for this subarea alone, using [tiab]/[mh]"}},
                "required": ["name", "pubmed_clause"], "additionalProperties": False,
            },
        },
    },
    "required": ["synonyms", "mesh_terms", "pubmed_query", "web_queries", "subtopics"],
    "additionalProperties": False,
}


def expand_terms(topic: str, llm_cfg: dict) -> dict:
    return llm.structured((
        f"Topic for this week's AI-in-medicine spotlight: {topic}\n\n"
        "List the synonyms, abbreviations and closely related terms researchers and industry use for this "
        "topic (e.g. for Electronic Health Records: EHR, EMR, electronic medical records, clinical notes, "
        "health information systems, FHIR), the matching MeSH headings, a PubMed query that captures the "
        "topic, web search queries that would surface the latest AI developments in it, and 6-8 subareas "
        "of the topic (e.g. for EHR: clinical notes NLP, risk prediction, phenotyping, coding and billing, "
        "interoperability, patient portals) that will be cross-tabulated against evidence quality and "
        "populations to find research gaps."), TERMS_SCHEMA, llm_cfg, effort="medium", max_tokens=8000)


# ---------- 2. publication trend (real counts from PubMed) ----------

def _count(term: str) -> int:
    time.sleep(0.12 if "api_key" in _ncbi_params() else 0.4)  # NCBI: 10 req/s with a key, 3 without
    r = session().get(f"{EUTILS}/esearch.fcgi", params={
        **_ncbi_params(), "db": "pubmed", "term": term, "retmode": "json", "rettype": "count"}, timeout=30)
    r.raise_for_status()
    return int(r.json()["esearchresult"]["count"])


def pubmed_trend(topic_query: str, end: date, years: int = 10) -> dict:
    rows = []
    for y in range(end.year - years + 1, end.year + 1):
        window = f'("{y}/01/01"[dp] : "{y}/12/31"[dp])'
        topic_n = _count(f"({topic_query}) AND {window}")
        ai_n = _count(f"({topic_query}) AND {AI_CLAUSE} AND {window}")
        rows.append({"year": y, "topic": topic_n, "topic_ai": ai_n,
                     "ai_share_pct": round(100 * ai_n / topic_n, 1) if topic_n else 0.0})
    return {"query": topic_query, "ai_clause": AI_CLAUSE, "rows": rows, "partial_year": end.year}


# ---------- 3. gap map: where AI work is thin ----------

# Columns of the gap map. Each restricts AI + subtopic papers to an evidence stage or population.
FACETS = {
    "External validation": '("external validation"[tiab] OR "externally validated"[tiab] OR "multicenter"[tiab] OR "multi-site"[tiab])',
    "Prospective": '(prospective[tiab] OR "Prospective Studies"[mh])',
    "RCT": '("Randomized Controlled Trial"[pt] OR randomized[ti] OR randomised[ti])',
    "Deployment / implementation": '(implementation[tiab] OR deployment[tiab] OR deployed[tiab] OR "real-world"[tiab] OR "clinical workflow"[tiab])',
    "Pediatric": '(child*[tiab] OR pediatric*[tiab] OR paediatric*[tiab] OR neonat*[tiab] OR "Child"[mh])',
    "Low-resource / LMIC": '("low-resource"[tiab] OR "resource-limited"[tiab] OR LMIC*[tiab] OR "low- and middle-income"[tiab] OR "Developing Countries"[mh] OR rural[tiab])',
    "Fairness / bias": '(fairness[tiab] OR bias[tiab] OR disparit*[tiab] OR equity[tiab])',
}


def gap_map(topic_query: str, subtopics: list[dict], end: date, years: int = 5) -> dict:
    window = f'("{end.year - years + 1}/01/01"[dp] : "{end:%Y/%m/%d}"[dp])'
    rows = []
    for st in subtopics:
        base = f"({topic_query}) AND ({st['pubmed_clause']}) AND {AI_CLAUSE} AND {window}"
        try:
            total = _count(base)
            cells = {name: _count(f"{base} AND {clause}") for name, clause in FACETS.items()}
        except Exception as e:
            log.warning("gap map row %s failed: %s", st["name"], e)
            continue
        rows.append({"subtopic": st["name"], "ai_papers": total, "counts": cells,
                     "pct": {k: round(100 * v / total, 1) if total else 0.0 for k, v in cells.items()}})
    overall = None
    try:
        base = f"({topic_query}) AND {AI_CLAUSE} AND {window}"
        overall = {"years": f"{end.year - years + 1}-{end.year}", "total": _count(base),
                   "counts": {name: _count(f"{base} AND {clause}") for name, clause in FACETS.items()}}
    except Exception as e:
        log.warning("topic-wide facet counts failed: %s", e)
    return {"years": f"{end.year - years + 1}-{end.year}", "facets": list(FACETS), "rows": rows, "overall": overall}


def gap_map_text(gm: dict) -> str:
    lines = [f"Subarea | AI papers {gm['years']} | " + " | ".join(gm["facets"])]
    for r in gm["rows"]:
        lines.append(f"{r['subtopic']} | {r['ai_papers']} | " +
                     " | ".join(f"{r['counts'][f]} ({r['pct'][f]}%)" for f in gm["facets"]))
    return "\n".join(lines)


# ---------- 4. web research ----------

RESEARCH_PROMPT = """You are writing the Topic Spotlight for this week's BioMed AI Watch, a newsletter on AI in medicine
for clinicians, biomedical researchers, and research administrators. Today is {today}.

Topic: {topic}
Also search under: {synonyms}
MeSH: {mesh}
Suggested starting queries: {queries}

PubMed publication trend for AI + this topic (real counts, already charted for readers):
{trend}

Gap map: AI papers per subarea over the last five years, and how many reach each evidence stage or
population (count, % of that subarea). Low percentages are candidate gaps. Readers see this as a heatmap:
{gap_map}

Evidence funnel, all AI papers on the topic in the last five years and how many reach each stage:
{funnel}

The purpose of the spotlight is to discover NOVEL, specific research gaps in medical AI for this topic:
questions that are important, under-studied, and answerable now. Use the gap map as quantitative
evidence, then use the web to check each candidate: is someone already closing it (recent trials,
preprints, funded grants, products)? Is it blocked by data, regulation, or incentives? Discard gaps that
recent work already covers, and say so.

Search the web thoroughly for the most recent (prioritise the last 90 days) AI developments in this topic:
new studies and preprints, deployments at health systems, product launches and regulatory actions,
funding and partnerships, policy and standards, and expert critiques. Open the most important sources to
confirm details. Prefer primary sources (journals, FDA, NIH, company and health-system announcements).

Readers skim this between clinics, next to the charts. Be brief: at most 350 words in total, one line per
bullet, no bullet over 30 words. Write the spotlight in Markdown, starting at heading level 3:
### Key takeaways   (exactly 3 bullets: the most important things a reader should know)
### What's new       (4-5 bullets, each "**Mon D** — what happened [source](url)")
### Novel gaps       (exactly 3, ranked, as a numbered list. Each item is one line:
                     "**The gap.** Evidence: a figure + [source](url). Study: design, data, endpoint. Funder: who.")
### Outlook          (one sentence)

Every factual claim needs an inline link to the page it came from. Don't state anything you didn't find.
Gaps must survive your checks: drop any that recent work already covers.

If your sources contain a quantitative series that exposes a gap (e.g. FDA-cleared devices vs. devices
with prospective evidence, adoption by hospital type, funding by subarea, representation of populations in
datasets), end with ONE fenced block tagged `chart` holding JSON:
{{"title": str (max 45 characters), "type": "line"|"bar", "x_label": str, "y_label": str, "x": [labels],
  "series": [{{"name": str, "values": [numbers]}}], "source": "publisher name and URL"}}
Use only numbers taken from a source you read. Omit the block if there's nothing solid to chart."""


def research(topic: str, terms: dict, trend: dict, gm: dict, today: date,
             llm_cfg: dict) -> tuple[str, dict | None, dict]:
    trend_txt = "\n".join(f"{r['year']}: {r['topic_ai']} AI papers ({r['ai_share_pct']}% of {r['topic']})"
                          for r in trend["rows"])
    prompt = RESEARCH_PROMPT.format(
        today=today.isoformat(), topic=topic, synonyms=", ".join(terms["synonyms"]),
        mesh=", ".join(terms["mesh_terms"]), queries="; ".join(terms["web_queries"]), trend=trend_txt,
        gap_map=gap_map_text(gm), funnel=_funnel_text(gm.get("overall")))
    text = llm.web_research(prompt, llm_cfg).strip()
    captions = {}
    m = re.search(r"```captions\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = (text[: m.start()] + text[m.end():]).strip()
        try:
            captions = {k: str(v) for k, v in json.loads(m.group(1)).items()}
        except ValueError as e:
            log.warning("discarding malformed captions: %s", e)
    spec = None
    m = re.search(r"```chart\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = text[: m.start()].rstrip()
        try:
            spec = json.loads(m.group(1))
            assert all(len(s["values"]) == len(spec["x"]) for s in spec["series"])
        except (ValueError, KeyError, AssertionError) as e:
            log.warning("discarding malformed chart spec: %s", e)
            spec = None
    return text, spec, captions


def _funnel_text(overall: dict | None) -> str:
    if not overall:
        return "(not available)"
    return f"{overall['total']}: " + ", ".join(f"{k} {v}" for k, v in overall["counts"].items())


# ---------- orchestration ----------

def build(cfg: dict, end: date, override: str | None = None) -> dict:
    """Returns the spotlight: topic, terms, PubMed trend and gap map, markdown, and any web-sourced series."""
    topic = pick_topic(cfg, end, override)
    log.info("spotlight topic: %s", topic)

    terms = expand_terms(topic, cfg["llm"])
    query = terms["pubmed_query"]
    try:
        if _count(query) == 0:
            raise ValueError("query matched nothing")
    except Exception as e:
        log.warning("model PubMed query unusable (%s); falling back to plain terms", e)
        query = " OR ".join(f'"{t}"[tiab]' for t in [topic, *terms["synonyms"]])

    trend = pubmed_trend(query, end)
    gm = gap_map(query, terms["subtopics"], end)
    markdown, spec, _ = research(topic, terms, trend, gm, end, cfg["llm"])

    # Charts are chosen and drawn later, from all of the issue's data (see charts.py).
    return {"topic": topic, "terms": terms, "trend": trend, "gap_map": gm, "markdown": markdown,
            "chart_spec": spec}
