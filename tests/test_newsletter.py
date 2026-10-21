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
    assert "## 4. Research gaps" in md and "$512,345" in md and "_(recurring)_" in md
    html = render_email_html(md, "BioMed AI Watch", "https://example.org/issues/2026-10-21")
    assert "{{UNSUBSCRIBE_URL}}" in html and "<h2" in html and "title:" not in html
    assert "2/2 b" in render_social(a, "")
