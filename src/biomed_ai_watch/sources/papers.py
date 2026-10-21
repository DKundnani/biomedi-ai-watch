"""AI-in-medicine papers from PubMed, arXiv, and medRxiv."""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import date

import feedparser

from ..http import session
from ..models import Item

log = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _ncbi_params() -> dict:
    p = {"tool": "biomed-ai-watch"}
    if os.getenv("NCBI_API_KEY"):
        p["api_key"] = os.environ["NCBI_API_KEY"]
    if os.getenv("NCBI_EMAIL"):
        p["email"] = os.environ["NCBI_EMAIL"]
    return p


def pubmed(cfg: dict, start: date, end: date) -> list[Item]:
    s = session()
    base = _ncbi_params()
    r = s.get(f"{EUTILS}/esearch.fcgi", params={
        **base, "db": "pubmed", "term": cfg["papers"]["pubmed_query"], "retmode": "json",
        "datetype": "edat", "mindate": start.strftime("%Y/%m/%d"), "maxdate": end.strftime("%Y/%m/%d"),
        "retmax": cfg["papers"]["max_per_source"], "sort": "relevance",
    }, timeout=30)
    r.raise_for_status()
    ids = r.json()["esearchresult"]["idlist"]
    if not ids:
        return []
    r = s.get(f"{EUTILS}/efetch.fcgi", params={**base, "db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
              timeout=60)
    r.raise_for_status()
    items = []
    for art in ET.fromstring(r.content).iter("PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.iter("AbstractText"))
        journal = art.findtext(".//Journal/Title", "")
        doi = next((e.text for e in art.iter("ArticleId") if e.get("IdType") == "doi"), "")
        items.append(Item(
            id=f"pmid:{pmid}", kind="paper", source="PubMed", title=title.strip(),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", date=end.isoformat(), summary=abstract,
            extra={"journal": journal, "doi": doi},
        ))
    return items


def arxiv(cfg: dict, start: date, end: date) -> list[Item]:
    window = f"submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]"
    r = session().get("https://export.arxiv.org/api/query", params={
        "search_query": f"({cfg['papers']['arxiv_query']}) AND {window}",
        "max_results": cfg["papers"]["max_per_source"], "sortBy": "submittedDate", "sortOrder": "descending",
    }, timeout=60)
    r.raise_for_status()
    items = []
    for e in feedparser.parse(r.text).entries:
        arxiv_id = e.id.rsplit("/", 1)[-1]
        items.append(Item(
            id=f"arxiv:{arxiv_id}", kind="paper", source="arXiv", title=" ".join(e.title.split()),
            url=e.link, date=e.published[:10], summary=" ".join(e.summary.split()),
            extra={"categories": ", ".join(t.term for t in e.get("tags", []))},
        ))
    return items


def medrxiv(cfg: dict, start: date, end: date) -> list[Item]:
    s = session()
    keywords = [k.lower() for k in cfg["papers"]["medrxiv_keywords"]]
    items, cursor = [], 0
    while True:
        r = s.get(f"https://api.biorxiv.org/details/medrxiv/{start}/{end}/{cursor}", timeout=60)
        r.raise_for_status()
        data = r.json()
        batch = data.get("collection", [])
        for p in batch:
            text = f"{p['title']} {p['abstract']}".lower()
            if any(k in text for k in keywords):
                items.append(Item(
                    id=f"doi:{p['doi']}", kind="paper", source="medRxiv", title=p["title"],
                    url=f"https://www.medrxiv.org/content/{p['doi']}v{p['version']}", date=p["date"],
                    summary=p["abstract"], extra={"category": p.get("category"), "preprint": "yes"},
                ))
        cursor += len(batch)
        total = int(data.get("messages", [{}])[0].get("total", 0))
        if not batch or cursor >= total or len(items) >= cfg["papers"]["max_per_source"]:
            break
    return items[: cfg["papers"]["max_per_source"]]


def collect(cfg: dict, start: date, end: date) -> list[Item]:
    items: list[Item] = []
    for fn in (pubmed, arxiv, medrxiv):
        try:
            got = fn(cfg, start, end)
            log.info("papers/%s: %d", fn.__name__, len(got))
            items += got
        except Exception as e:  # one dead source shouldn't sink the issue
            log.warning("papers/%s failed: %s", fn.__name__, e)
    return items
