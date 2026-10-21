"""Weekly Topic Spotlight: expand a topic into search terms, measure its publication trend,
research recent developments on the web, and chart what's found."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path

import anthropic

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


def _stream(client: anthropic.Anthropic, llm_cfg: dict, messages: list, **kw):
    with client.beta.messages.stream(
        model=llm_cfg["model"], max_tokens=llm_cfg["max_tokens"], messages=messages,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw,
    ) as s:
        msg = s.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request: {msg.stop_details}")
    return msg


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


def expand_terms(client: anthropic.Anthropic, topic: str, llm_cfg: dict) -> dict:
    msg = _stream(client, {**llm_cfg, "max_tokens": 8000}, [{"role": "user", "content": (
        f"Topic for this week's AI-in-medicine spotlight: {topic}\n\n"
        "List the synonyms, abbreviations and closely related terms researchers and industry use for this "
        "topic (e.g. for Electronic Health Records: EHR, EMR, electronic medical records, clinical notes, "
        "health information systems, FHIR), the matching MeSH headings, a PubMed query that captures the "
        "topic, web search queries that would surface the latest AI developments in it, and 6-8 subareas "
        "of the topic (e.g. for EHR: clinical notes NLP, risk prediction, phenotyping, coding and billing, "
        "interoperability, patient portals) that will be cross-tabulated against evidence quality and "
        "populations to find research gaps.")}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": TERMS_SCHEMA}})
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


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


def plot_trend(topic: str, trend: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = trend["rows"]
    years = [str(r["year"]) + (" (YTD)" if r["year"] == trend["partial_year"] else "") for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    ax.bar(years, [r["topic_ai"] for r in rows], color="#0b5c6b")
    ax.set_ylabel("AI papers on PubMed")
    ax.tick_params(axis="x", rotation=45)
    ax2 = ax.twinx()
    ax2.plot(years, [r["ai_share_pct"] for r in rows], color="#cf4310", marker="o", linewidth=2)
    ax2.set_ylabel("% of all papers on the topic", color="#cf4310")
    ax2.set_ylim(bottom=0)
    for a in (ax, ax2):
        a.spines["top"].set_visible(False)
    ax.set_title(f"AI research on {topic}: publications per year and share of the field", fontsize=11)
    fig.text(0.01, 0.01, "Source: PubMed E-utilities counts", fontsize=7, color="#666")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def plot_spec(spec: dict, path: Path) -> None:
    """Render a chart the model proposed from figures it found in its sources."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    n = len(spec["series"])
    for k, s in enumerate(spec["series"]):
        if spec.get("type") == "bar":
            w = 0.8 / n
            ax.bar([i + k * w for i in range(len(spec["x"]))], s["values"], width=w, label=s["name"])
            ax.set_xticks([i + 0.4 - w / 2 for i in range(len(spec["x"]))], spec["x"])
        else:
            ax.plot(spec["x"], s["values"], marker="o", linewidth=2, label=s["name"])
    ax.set_title(spec["title"], fontsize=11)
    ax.set_xlabel(spec.get("x_label", ""))
    ax.set_ylabel(spec.get("y_label", ""))
    ax.spines[["top", "right"]].set_visible(False)
    if n > 1:
        ax.legend(frameon=False)
    fig.text(0.01, 0.01, f"Source: {spec.get('source', '')}"[:160], fontsize=7, color="#666")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


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
    return {"years": f"{end.year - years + 1}-{end.year}", "facets": list(FACETS), "rows": rows}


def plot_gap_map(topic: str, gm: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows, facets = gm["rows"], gm["facets"]
    data = [[r["pct"][f] for f in facets] for r in rows]
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(rows) + 2.2), dpi=150)
    im = ax.imshow(data, cmap="YlGnBu", aspect="auto", vmin=0)
    ax.set_xticks(range(len(facets)), facets, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(rows)), [f"{r['subtopic']} (n={r['ai_papers']:,})" for r in rows], fontsize=8)
    vmax = max((v for row in data for v in row), default=1) or 1
    for i, r in enumerate(rows):
        for j, f in enumerate(facets):
            ax.text(j, i, f"{r['counts'][f]:,}\n{r['pct'][f]:.0f}%", ha="center", va="center", fontsize=6.5,
                    color="white" if r["pct"][f] > vmax * 0.6 else "#1d2327")
    fig.colorbar(im, ax=ax, label="% of the subarea's AI papers", shrink=0.8)
    ax.set_title(f"Gap map: AI research on {topic}, {gm['years']}\n"
                 "Pale cells = little evidence at that stage or for that population", fontsize=10)
    fig.text(0.01, 0.01, "Source: PubMed E-utilities counts; facet matching is keyword-based and approximate",
             fontsize=6.5, color="#666")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


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

The purpose of the spotlight is to discover NOVEL, specific research gaps in medical AI for this topic:
questions that are important, under-studied, and answerable now. Use the gap map as quantitative
evidence, then use the web to check each candidate: is someone already closing it (recent trials,
preprints, funded grants, products)? Is it blocked by data, regulation, or incentives? Discard gaps that
recent work already covers, and say so.

Search the web thoroughly for the most recent (prioritise the last 90 days) AI developments in this topic:
new studies and preprints, deployments at health systems, product launches and regulatory actions,
funding and partnerships, policy and standards, and expert critiques. Open the most important sources to
confirm details. Prefer primary sources (journals, FDA, NIH, company and health-system announcements).

Then write the spotlight in Markdown (about 900-1300 words), starting at heading level 3:
### Why it matters now
### Recent developments   (dated bullets, each with an inline [source](url) link)
### What the numbers show (interpret the trend and the gap map: where the field is crowded, where it is thin)
### Novel research gaps   (3-5 gaps, ranked. For each: **the gap** in one sentence; evidence (gap-map
                          figures and sources); why it is still open (what you checked); a concrete study
                          that would close it (design, data source, endpoint); who could fund it)
### Outlook

Every factual claim needs an inline link to the page it came from. Don't state anything you didn't find.

If your sources contain a quantitative series that exposes a gap (e.g. FDA-cleared devices vs. devices
with prospective evidence, adoption by hospital type, funding by subarea, representation of populations in
datasets), end with ONE fenced block tagged `chart` holding JSON:
{{"title": str, "type": "line"|"bar", "x_label": str, "y_label": str, "x": [labels],
  "series": [{{"name": str, "values": [numbers]}}], "source": "publisher name and URL"}}
Use only numbers taken from a source you read. Omit the block if there's nothing solid to chart."""


def research(client: anthropic.Anthropic, topic: str, terms: dict, trend: dict, gm: dict, today: date,
             llm_cfg: dict) -> tuple[str, dict | None]:
    trend_txt = "\n".join(f"{r['year']}: {r['topic_ai']} AI papers ({r['ai_share_pct']}% of {r['topic']})"
                          for r in trend["rows"])
    prompt = RESEARCH_PROMPT.format(
        today=today.isoformat(), topic=topic, synonyms=", ".join(terms["synonyms"]),
        mesh=", ".join(terms["mesh_terms"]), queries="; ".join(terms["web_queries"]), trend=trend_txt,
        gap_map=gap_map_text(gm))
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 15},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10}]
    messages = [{"role": "user", "content": prompt}]

    for _ in range(6):  # server tools may pause a long turn; re-send to let it continue
        msg = _stream(client, llm_cfg, messages, tools=tools,
                      output_config={"effort": llm_cfg["effort"]})
        if msg.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": msg.content}]
    log.info("spotlight research: stop=%s in=%s out=%s request=%s", msg.stop_reason,
             msg.usage.input_tokens, msg.usage.output_tokens, msg._request_id)

    text = "".join(b.text for b in msg.content if b.type == "text").strip()
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
    return text, spec


# ---------- orchestration ----------

def build(cfg: dict, end: date, assets_dir: Path, override: str | None = None) -> dict:
    """Returns {"topic", "terms", "trend", "markdown", "charts": [relative paths]}."""
    client = anthropic.Anthropic()
    topic = pick_topic(cfg, end, override)
    log.info("spotlight topic: %s", topic)

    terms = expand_terms(client, topic, cfg["llm"])
    query = terms["pubmed_query"]
    try:
        if _count(query) == 0:
            raise ValueError("query matched nothing")
    except Exception as e:
        log.warning("model PubMed query unusable (%s); falling back to plain terms", e)
        query = " OR ".join(f'"{t}"[tiab]' for t in [topic, *terms["synonyms"]])

    trend = pubmed_trend(query, end)
    charts = []
    trend_png = assets_dir / f"{end}-spotlight-trend.png"
    plot_trend(topic, trend, trend_png)
    charts.append(trend_png.name)

    gm = gap_map(query, terms["subtopics"], end)
    if gm["rows"]:
        gap_png = assets_dir / f"{end}-spotlight-gapmap.png"
        plot_gap_map(topic, gm, gap_png)
        charts.append(gap_png.name)

    markdown, spec = research(client, topic, terms, trend, gm, end, cfg["llm"])
    if spec:
        try:
            extra_png = assets_dir / f"{end}-spotlight-chart.png"
            plot_spec(spec, extra_png)
            charts.append(extra_png.name)
        except Exception as e:
            log.warning("could not render model chart: %s", e)
    return {"topic": topic, "terms": terms, "trend": trend, "gap_map": gm, "markdown": markdown, "charts": charts,
            "chart_spec": spec}
