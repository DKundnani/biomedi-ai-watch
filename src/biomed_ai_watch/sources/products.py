"""Pharma and medical product updates: FDA 510(k) clearances, FDA/industry news feeds."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from time import mktime

import feedparser

from ..http import session
from ..models import Item

log = logging.getLogger(__name__)


def fda_510k(cfg: dict, start: date, end: date) -> list[Item]:
    r = session().get("https://api.fda.gov/device/510k.json", params={
        "search": f"decision_date:[{start:%Y%m%d} TO {end:%Y%m%d}]", "limit": 1000,
    }, timeout=60)
    if r.status_code == 404:  # openFDA returns 404 for "no matches"
        return []
    r.raise_for_status()
    kws = [k.lower() for k in cfg["products"]["device_keywords"]]
    items = []
    for d in r.json().get("results", []):
        name = d.get("device_name", "")
        if not any(k in name.lower() for k in kws):
            continue
        k = d["k_number"]
        dd = d.get("decision_date", "")
        items.append(Item(
            id=f"510k:{k}", kind="product", source="FDA 510(k)", title=f"{name} ({d.get('applicant', '')})",
            url=f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k}",
            date=f"{dd[:4]}-{dd[4:6]}-{dd[6:]}" if len(dd) == 8 else dd,
            summary=f"510(k) {d.get('decision_description', '')}. Product code {d.get('product_code', '')}; "
                    f"advisory committee: {d.get('advisory_committee_description', '')}.",
            extra={"applicant": d.get("applicant"), "product_code": d.get("product_code")},
        ))
    return items[: cfg["products"]["max_per_source"]]


def rss(cfg: dict, start: date, end: date) -> list[Item]:
    pattern = re.compile("|".join(re.escape(k) for k in cfg["products"]["rss_keywords"]), re.I)
    items = []
    for feed in cfg["products"]["rss_feeds"]:
        try:
            parsed = feedparser.parse(feed["url"], agent="BioMedAIWatch/0.1")
        except Exception as e:
            log.warning("rss %s failed: %s", feed["name"], e)
            continue
        for e in parsed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            d = datetime.fromtimestamp(mktime(ts)).date() if ts else end
            summary = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
            if not (start <= d <= end) or not pattern.search(f"{e.get('title', '')} {summary}"):
                continue
            items.append(Item(
                id=f"rss:{e.get('id') or e.link}", kind="product", source=feed["name"], title=e.title,
                url=e.link, date=d.isoformat(), summary=" ".join(summary.split()),
            ))
    return items[: cfg["products"]["max_per_source"] * 2]


def collect(cfg: dict, start: date, end: date) -> list[Item]:
    items: list[Item] = []
    for fn in (fda_510k, rss):
        try:
            got = fn(cfg, start, end)
            log.info("products/%s: %d", fn.__name__, len(got))
            items += got
        except Exception as e:
            log.warning("products/%s failed: %s", fn.__name__, e)
    return items
