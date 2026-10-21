"""Newly awarded AI-in-medicine grants from NIH RePORTER and NSF."""
from __future__ import annotations

import logging
from datetime import date

from ..http import session
from ..models import Item

log = logging.getLogger(__name__)


def nih_reporter(cfg: dict, start: date, end: date) -> list[Item]:
    body = {
        "criteria": {
            "award_notice_date": {"from_date": start.isoformat(), "to_date": end.isoformat()},
            "advanced_text_search": {
                "operator": "or", "search_field": "projecttitle,abstracttext",
                "search_text": " ".join(f'"{k}"' for k in cfg["grants"]["keywords"]),
            },
        },
        "include_fields": ["ApplId", "ProjectNum", "ProjectTitle", "AbstractText", "AwardAmount",
                           "AwardNoticeDate", "Organization", "PrincipalInvestigators", "AgencyIcAdmin",
                           "ProjectDetailUrl"],
        "limit": cfg["grants"]["max_per_source"], "offset": 0,
        "sort_field": "award_amount", "sort_order": "desc",
    }
    r = session().post("https://api.reporter.nih.gov/v2/projects/search", json=body, timeout=60)
    r.raise_for_status()
    items = []
    for p in r.json().get("results", []):
        pis = ", ".join(pi.get("full_name", "") for pi in p.get("principal_investigators") or [])
        org = (p.get("organization") or {}).get("org_name", "")
        ic = (p.get("agency_ic_admin") or {}).get("abbreviation", "")
        items.append(Item(
            id=f"nih:{p['project_num']}", kind="grant", source=f"NIH {ic}".strip(), title=p["project_title"],
            url=p.get("project_detail_url") or f"https://reporter.nih.gov/project-details/{p['appl_id']}",
            date=(p.get("award_notice_date") or end.isoformat())[:10], summary=p.get("abstract_text") or "",
            extra={"amount_usd": p.get("award_amount"), "institution": org, "pi": pis},
        ))
    return items


def nsf(cfg: dict, start: date, end: date) -> list[Item]:
    s = session()
    seen, items = set(), []
    for kw in cfg["grants"]["keywords"]:
        r = s.get("https://api.nsf.gov/services/v1/awards.json", params={
            "keyword": f'"{kw}" health',
            "dateStart": start.strftime("%m/%d/%Y"), "dateEnd": end.strftime("%m/%d/%Y"),
            "printFields": "id,title,abstractText,fundsObligatedAmt,awardeeName,piFirstName,piLastName,date",
            "rpp": 25,
        }, timeout=60)
        r.raise_for_status()
        for a in r.json().get("response", {}).get("award", []):
            text = f"{a['title']} {a.get('abstractText', '')}".lower()
            if a["id"] in seen or not any(k.lower() in text for k in cfg["grants"]["keywords"]):
                continue
            seen.add(a["id"])
            m, d, y = a.get("date", "").split("/") if a.get("date") else ("", "", "")
            items.append(Item(
                id=f"nsf:{a['id']}", kind="grant", source="NSF", title=a["title"],
                url=f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={a['id']}",
                date=f"{y}-{m}-{d}" if y else end.isoformat(), summary=a.get("abstractText", ""),
                extra={"amount_usd": a.get("fundsObligatedAmt"), "institution": a.get("awardeeName"),
                       "pi": f"{a.get('piFirstName', '')} {a.get('piLastName', '')}".strip()},
            ))
    return items[: cfg["grants"]["max_per_source"]]


def collect(cfg: dict, start: date, end: date) -> list[Item]:
    items: list[Item] = []
    for fn in (nih_reporter, nsf):
        try:
            got = fn(cfg, start, end)
            log.info("grants/%s: %d", fn.__name__, len(got))
            items += got
        except Exception as e:
            log.warning("grants/%s failed: %s", fn.__name__, e)
    return items
