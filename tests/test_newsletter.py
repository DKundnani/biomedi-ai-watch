from biomed_ai_watch.analysis import _drop_unknown_ids
from biomed_ai_watch.models import Item
from biomed_ai_watch.newsletter import render_email_html, render_issue, render_social

ITEMS = [
    Item("pmid:1", "paper", "PubMed", "LLM triage in the ED", "https://pubmed.ncbi.nlm.nih.gov/1/", "2026-10-20",
         "abstract", {"journal": "NEJM AI"}),
    Item("nih:R01X", "grant", "NIH NCI", "AI for pathology", "https://reporter.nih.gov/x", "2026-10-19", "",
         {"amount_usd": 512345, "institution": "UNM"}),
    Item("510k:K1", "product", "FDA 510(k)", "AI chest X-ray triage (Acme)", "https://fda.gov/k1", "2026-10-18"),
]

ANALYSIS = {
    "headline": "LLMs reach the emergency department",
    "tldr": ["One", "Two", "Three"],
    "paper_themes": [{"theme": "Triage", "summary": "LLMs in triage.", "ids": ["pmid:1", "pmid:999"]}],
    "top_papers": [{"id": "pmid:1", "note": "First prospective study."}, {"id": "pmid:404", "note": "made up"}],
    "grants_summary": "NCI funds pathology AI.",
    "top_grants": [{"id": "nih:R01X", "note": "Large award."}],
    "products_summary": "One clearance.",
    "top_products": [{"id": "510k:K1", "note": "Radiology triage."}],
    "research_gaps": [{"gap": "No pediatric validation", "evidence": "All adult cohorts.", "ids": ["pmid:1"],
                       "suggested_study": "Multi-site pediatric validation.", "recurring": True}],
    "social": {"linkedin_post": "Post", "x_thread": ["a", "b"], "bluesky_post": "Sky"},
}


def test_unknown_ids_are_dropped():
    a = _drop_unknown_ids({**ANALYSIS, "paper_themes": [dict(t) for t in ANALYSIS["paper_themes"]]},
                          {i.id for i in ITEMS})
    assert [h["id"] for h in a["top_papers"]] == ["pmid:1"]
    assert a["paper_themes"][0]["ids"] == ["pmid:1"]


def test_render_issue_and_email():
    a = _drop_unknown_ids({**ANALYSIS}, {i.id for i in ITEMS})
    md = render_issue(a, ITEMS, "BioMed AI Watch", "week ending October 21, 2026", "2026-10-21")
    assert "## Gaps in this week's research" in md and "$512,345" in md and "_(recurring)_" in md
    html = render_email_html(md, "BioMed AI Watch", "https://example.org/issues/2026-10-21")
    assert "{{UNSUBSCRIBE_URL}}" in html and "<h2" in html and "title:" not in html
    assert "2/2 b" in render_social(a, "")


def test_site_publish(tmp_path):
    from biomed_ai_watch import site
    (tmp_path / "newsletter").mkdir()
    (tmp_path / "newsletter" / "_template.html").write_text(
        "<h1>{{TITLE}}</h1><p>{{SUBTITLE}}</p>{{TAG}}{{SHARE}}{{TOC}}{{CONTENT}}<a href='{{URL}}'>\n{{NAV}}\n")
    (tmp_path / "newsletter.html").write_text(
        "a<!-- latest:start -->x<!-- latest:end --><!-- issues:start -->old<!-- issues:end -->"
        "<!-- topics:start --><!-- topics:end -->b")
    a = _drop_unknown_ids({**ANALYSIS, "subtitle": "Deck line"}, {i.id for i in ITEMS})
    md = render_issue(a, ITEMS, "BioMed AI Watch", "week ending October 21, 2026", "2026-10-21")
    for d, t in [("2026-10-14", "Older & wiser"), ("2026-10-21", a["headline"])]:
        entry = {"date": d, "title": t, "subtitle": "Deck line", "topic": "EHR", "cover": None,
                 "read_min": 4, "description": "d"}
        issues = site.save_index(tmp_path, entry)
        page = site.write_issue_page(tmp_path, entry, md, [], issues)
        site.refresh_neighbours(tmp_path, issues)
    out = page.read_text()
    assert "<h1>LLMs reach the emergency department</h1>" in out and "<p>Deck line</p>" in out
    assert "In brief" in out and "# BioMed" not in out and "<h4>" not in out
    assert 'id="research"' in out and 'class="issue-toc"' in out and "Spotlight: EHR" in out
    assert "linkedin.com/sharing" in out and "Older &amp; wiser" in out  # previous-issue link
    assert "LLMs reach" in (tmp_path / "newsletter" / "2026-10-14.html").read_text()  # its next link
    site.update_index_page(tmp_path, issues)
    home = (tmp_path / "newsletter.html").read_text()
    assert "old" not in home and 'class="nl-latest" href="newsletter/2026-10-21.html"' in home
    assert 'href="newsletter/2026-10-14.html"' in home and "Older &amp; wiser" in home


def test_chart_plan_and_render(tmp_path):
    from biomed_ai_watch import charts
    sp = {"topic": "EHR", "chart_spec": {"title": "Devices", "x_label": "yr", "y_label": "n", "source": "FDA",
                                         "x": ["2024", "2025", "2026"], "series": [{"name": "cleared", "values": [1, 2, 4]}]},
          "trend": {"rows": [{"year": y, "topic": 900 + y, "topic_ai": y % 7 + 3, "ai_share_pct": 2.5}
                             for y in range(2017, 2027)], "partial_year": 2026},
          "gap_map": {"years": "2022-2026", "facets": ["External validation", "RCT", "Deployment / implementation"],
                      "rows": [{"subtopic": f"Sub {k}", "ai_papers": 40 * k,
                                "pct": {"External validation": 10.0 * k, "RCT": 1.0, "Deployment / implementation": 30.0},
                                "counts": {"External validation": 4 * k, "RCT": 1, "Deployment / implementation": 12}}
                               for k in range(1, 5)],
                      "overall": {"years": "2022-2026", "total": 400,
                                  "counts": {f: 12 for f in charts.STAGES}}}}
    ds = charts.datasets(ITEMS * 2, ANALYSIS, sp)
    assert {"pubmed_trend", "gap_map", "evidence_funnel", "web_series", "sources_scanned"} <= set(ds)
    bad = [{"section": "week", "title": "x", "charts": [{**charts.default_plan(ds)[0]["charts"][0], "x": "nope"}]}]
    assert charts.validate(bad, ds) == []
    done = charts.render(charts.default_plan(ds), ds, tmp_path, "2026-10-21")
    assert [s["section"] for s in done] == ["week", "spotlight", "spotlight"]
    assert all((tmp_path / s["file"]).stat().st_size > 10_000 for s in done)
    md = render_issue(_drop_unknown_ids({**ANALYSIS}, {i.id for i in ITEMS}), ITEMS, "B", "wk", "2026-10-21",
                      sp | {"terms": {"synonyms": ["EHR"]}, "markdown": "### Key takeaways"}, done)
    assert md.index(done[0]["file"]) < md.index("## Spotlight") < md.index(done[1]["file"])
