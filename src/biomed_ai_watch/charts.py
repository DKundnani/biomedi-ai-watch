"""Decide which charts to draw from this week's data, then draw them as two-chart slides.

The datasets are built from what the pipeline actually collected and counted. The chart-picker skill
(skills/chart-picker/SKILL.md) chooses chart types, pairings and takeaways; the plan only names datasets
and columns, so every number on a slide comes from the data. If planning fails, a fixed plan is used.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from . import llm, slides
from .config import ROOT
from .models import Item

log = logging.getLogger(__name__)
SKILL = ROOT / "skills" / "chart-picker" / "SKILL.md"
STAGES = ["External validation", "Prospective", "Deployment / implementation", "RCT"]
SHORT = {"External validation": "External validation", "Deployment / implementation": "Deployed",
         "Low-resource / LMIC": "Low-resource", "Fairness / bias": "Fairness"}


# ---------- datasets ----------

def datasets(items: list[Item], a: dict, sp: dict | None) -> dict:
    """{name: {"description", "section", "source", "rows": [dict]}} with no empty datasets."""
    ds = {}

    def add(name, section, description, source, rows):
        if rows:
            ds[name] = {"section": section, "description": description, "source": source, "rows": rows}

    feeds = "PubMed, arXiv, medRxiv, NIH RePORTER, NSF, openFDA, FDA and industry news"
    add("sources_scanned", "week", "Items collected this week, by source and kind (paper, grant, product)", feeds,
        [{"source": s, "kind": k, "items": n} for (s, k), n in Counter((i.source, i.kind) for i in items).most_common()])

    funders, insts = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for i in items:
        if i.kind == "grant":
            amt = float(i.extra.get("amount_usd") or 0)
            for table, key in ((funders, i.source.replace("NIH ", "")), (insts, i.extra.get("institution"))):
                if key:
                    table[key][0] += 1
                    table[key][1] += amt
    add("grants_by_funder", "week", "New AI grants this week: count and total dollars per funder", "NIH RePORTER, NSF",
        [{"funder": k, "grants": n, "total_usd": round(v)} for k, (n, v) in sorted(funders.items(), key=lambda kv: -kv[1][1])])
    add("grants_by_institution", "week", "New AI grants this week: count and total dollars per institution (top 12)",
        "NIH RePORTER, NSF",
        [{"institution": k, "grants": n, "total_usd": round(v)}
         for k, (n, v) in sorted(insts.items(), key=lambda kv: -kv[1][1])[:12]])
    add("papers_by_venue", "week", "Papers this week by journal or preprint server (top 12)", "PubMed, arXiv, medRxiv",
        [{"venue": v, "papers": n} for v, n in Counter(i.extra.get("journal") or i.source for i in items
                                                      if i.kind == "paper").most_common(12)])
    add("paper_themes", "week", "Themes the editor found in this week's papers, with how many papers each covers",
        "BioMed AI Watch analysis of this week's papers",
        [{"theme": t["theme"], "papers": len(t["ids"])} for t in a.get("paper_themes", [])])

    if sp:
        topic = sp["topic"]
        add("pubmed_trend", "spotlight", f"PubMed papers per year on {topic}: all papers, AI papers, AI share (%)",
            "PubMed E-utilities counts",
            [{"year": r["year"], "all_papers": r["topic"], "ai_papers": r["topic_ai"], "ai_share_pct": r["ai_share_pct"]}
             for r in sp["trend"]["rows"]])
        gm = sp["gap_map"]
        add("gap_map", "spotlight", f"AI papers on {topic} subareas ({gm['years']}): % reaching each evidence stage "
            "or population (long format). Low % = candidate gap", "PubMed E-utilities counts",
            [{"subtopic": r["subtopic"], "stage": SHORT.get(f, f), "pct": r["pct"][f], "papers": r["counts"][f]}
             for r in gm["rows"] for f in gm["facets"]])
        add("subtopic_volume_vs_validation", "spotlight",
            f"Per {topic} subarea: AI papers ({gm['years']}) vs % externally validated, % RCT, % deployed. "
            "High volume + low validation = hype; low volume = under-studied", "PubMed E-utilities counts",
            [{"subtopic": r["subtopic"], "ai_papers": r["ai_papers"],
              "external_validation_pct": r["pct"].get("External validation"), "rct_pct": r["pct"].get("RCT"),
              "deployment_pct": r["pct"].get("Deployment / implementation")} for r in gm["rows"]])
        if gm.get("overall"):
            o = gm["overall"]
            add("evidence_funnel", "spotlight", f"All AI papers on {topic} ({o['years']}) and how many reach each "
                "evidence stage", "PubMed E-utilities counts",
                [{"stage": "All AI papers", "papers": o["total"]}]
                + [{"stage": SHORT.get(s, s), "papers": o["counts"][s]} for s in STAGES])
        spec = sp.get("chart_spec")
        if spec:
            add("web_series", "spotlight", f"From the web research: {spec.get('title')}. x = {spec.get('x_label')}, "
                f"values = {spec.get('y_label')}", spec.get("source", "web sources"),
                [{"x": x, **{s["name"]: s["values"][j] for s in spec["series"]}} for j, x in enumerate(spec["x"])])
    return ds


# ---------- planning ----------

_CHART = {
    "type": "object",
    "properties": {
        "dataset": {"type": "string"},
        "type": {"type": "string", "enum": slides.TYPES},
        "x": {"type": "string", "description": "Category, time or numeric x column (heatmap: the column dimension)"},
        "y": {"type": "array", "items": {"type": "string"}, "description": "Value column(s)"},
        "y2": {"type": "string", "description": "line only: a second value on its own axis, else empty"},
        "label": {"type": "string", "description": "scatter: point labels; heatmap: the row dimension; else empty"},
        "size": {"type": "string", "description": "scatter only: column for point size, else empty"},
        "sort": {"type": "string", "enum": ["desc", "asc", "none"]},
        "top": {"type": "integer", "description": "Keep the first N rows after sorting; 0 for all"},
        "title": {"type": "string"}, "x_label": {"type": "string"}, "y_label": {"type": "string"},
        "value_format": {"type": "string", "enum": ["int", "pct", "usd_m"]},
        "wide": {"type": "boolean"},
        "takeaway": {"type": "string", "description": "At most 18 words, interpreting the chart"},
    },
    "required": ["dataset", "type", "x", "y", "y2", "label", "size", "sort", "top", "title", "x_label", "y_label",
                 "value_format", "wide", "takeaway"],
    "additionalProperties": False,
}
PLAN_SCHEMA = {
    "type": "object",
    "properties": {"slides": {"type": "array", "description": "2-3 slides", "items": {
        "type": "object",
        "properties": {"section": {"type": "string", "enum": ["week", "spotlight"]},
                       "title": {"type": "string"},
                       "charts": {"type": "array", "items": _CHART, "description": "1-2 charts"}},
        "required": ["section", "title", "charts"], "additionalProperties": False}}},
    "required": ["slides"], "additionalProperties": False,
}


def _catalogue(ds: dict) -> str:
    parts = []
    for name, d in ds.items():
        cols = list(d["rows"][0])
        parts.append(f"<dataset name=\"{name}\" section=\"{d['section']}\" rows=\"{len(d['rows'])}\">\n"
                     f"{d['description']}\ncolumns: {', '.join(cols)}\n"
                     + "\n".join(json.dumps(r) for r in d["rows"][:60]) + "\n</dataset>")
    return "\n\n".join(parts)


def plan(ds: dict, llm_cfg: dict) -> list[dict]:
    skill = SKILL.read_text().split("---", 2)[2]
    sections = sorted({d["section"] for d in ds.values()})
    prompt = (f"{_catalogue(ds)}\n\nPlan the slides for this issue: one slide for section \"week\""
              + (" and one or two for section \"spotlight\"" if "spotlight" in sections else "")
              + ". Follow the chart-picker guidance. Use only the datasets and columns listed.")
    out = llm.structured(prompt, PLAN_SCHEMA, llm_cfg, system=skill, effort="medium", max_tokens=8000)
    return validate(out["slides"], ds)


def validate(planned: list[dict], ds: dict) -> list[dict]:
    """Drop charts that name a missing dataset or column, and slides left empty."""
    ok_slides = []
    for s in planned:
        good = []
        for c in s["charts"][:2]:
            d = ds.get(c["dataset"])
            if not d or len(d["rows"]) < 2:
                log.warning("chart plan: unknown or tiny dataset %s", c["dataset"])
                continue
            cols = set(d["rows"][0])
            need = [c["x"], *c["y"]] + [c[k] for k in ("y2", "label", "size") if c.get(k)]
            if c["type"] == "heatmap" and not c.get("label"):
                need.append("<missing label>")
            if not c["y"] or any(n not in cols for n in need):
                log.warning("chart plan: %s uses columns %s not in %s", c["dataset"], need, sorted(cols))
                continue
            good.append(c)
        if good:
            ok_slides.append({**s, "charts": good})
    return ok_slides


def default_plan(ds: dict) -> list[dict]:
    """Used when the planner is unavailable: the fixed layout from before the chart picker."""
    blank = {"y2": "", "label": "", "size": "", "sort": "desc", "top": 9, "x_label": "", "y_label": "",
             "value_format": "int", "wide": False, "takeaway": ""}
    c = lambda **kw: {**blank, **kw}
    out = [{"section": "week", "title": "This week at a glance", "charts": [
        c(dataset="sources_scanned", type="barh", x="source", y=["items"], title="What we scanned, by source"),
        c(dataset="grants_by_funder", type="barh", x="funder", y=["total_usd"], value_format="usd_m",
          title="New AI grant dollars, by funder")]}]
    if "pubmed_trend" in ds:
        out.append({"section": "spotlight", "title": "How much AI work, and how mature", "charts": [
            c(dataset="pubmed_trend", type="line", x="year", y=["ai_papers"], y2="ai_share_pct", sort="none", top=0,
              title="AI papers per year and AI share", y_label="AI papers"),
            c(dataset="evidence_funnel", type="funnel", x="stage", y=["papers"], title="Evidence funnel")]})
        out.append({"section": "spotlight", "title": "Where the gaps are", "charts": [
            c(dataset="gap_map", type="heatmap", x="stage", y=["pct"], label="subtopic", value_format="pct",
              sort="none", top=0, wide=True, title="% of AI papers reaching each stage"),
            c(dataset="subtopic_volume_vs_validation", type="scatter", x="ai_papers", y=["external_validation_pct"],
              label="subtopic", sort="none", top=0, title="Volume vs validation", x_label="AI papers",
              y_label="% externally validated")]})
    return validate(out, ds)


# ---------- rendering ----------

def render(planned: list[dict], ds: dict, out_dir: Path, prefix: str) -> list[dict]:
    """Draw each slide. Returns [{"file", "section", "title", "captions"}]."""
    done, k = [], 0
    for n, s in enumerate(planned, 1):
        panels, widths = [], []
        for c in s["charts"]:
            panels.append(slides.chart(c, ds[c["dataset"]], k))
            widths.append(1.45 if c.get("wide") or c["type"] == "heatmap" else 1)
            k += 2
        sources = list(dict.fromkeys(ds[c["dataset"]]["source"] for c in s["charts"]))
        try:
            f = slides.slide(out_dir / f"{prefix}-slide-{n}.png", s["title"], panels, tuple(widths),
                             source="Source: " + "; ".join(sources))
        except Exception:
            log.exception("could not draw slide %s", s["title"])
            continue
        done.append({"file": f, "section": s["section"], "title": s["title"],
                     "captions": [c["takeaway"] for c in s["charts"] if c.get("takeaway")]})
    return done


def build(items: list[Item], a: dict, sp: dict | None, llm_cfg: dict, out_dir: Path, prefix: str) -> list[dict]:
    ds = datasets(items, a, sp)
    try:
        planned = plan(ds, llm_cfg)
        if not planned:
            raise ValueError("planner returned no usable charts")
    except Exception as e:
        log.warning("chart planning failed (%s); using the default layout", e)
        planned = default_plan(ds)
    log.info("chart plan: %s", [(s["title"], [c["type"] for c in s["charts"]]) for s in planned])
    return render(planned, ds, out_dir, prefix)
