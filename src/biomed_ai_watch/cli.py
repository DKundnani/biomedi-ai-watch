"""biomed-ai-watch command line: collect -> analyse -> publish."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from . import analysis, newsletter, spotlight
from .config import ROOT, load_config, week_window
from .models import Item
from .sources import grants, papers, products

log = logging.getLogger("biomed_ai_watch")
DATA, DOCS = ROOT / "data", ROOT / "docs"


def already_reported(current: str) -> set[str]:
    seen = set()
    for f in DATA.glob("*/analysis.json"):  # only issues that were actually published
        if f.parent.name == current:
            continue
        seen |= {i["id"] for i in json.loads((f.parent / "items.json").read_text())}
    return seen


def collect(cfg: dict, start: date, end: date) -> list[Item]:
    def lagged(section: str) -> date:
        return end - timedelta(days=cfg[section].get("lookback_days", cfg["lookback_days"]))

    items = (papers.collect(cfg, start, end) + grants.collect(cfg, lagged("grants"), end)
             + products.collect(cfg, lagged("products"), end))
    seen, unique = already_reported(end.isoformat()), []
    for i in items:
        if i.id not in seen:
            seen.add(i.id)
            unique.append(i)
    return unique


def past_gaps(limit_issues: int = 4) -> list[str]:
    gaps = []
    for f in sorted(DATA.glob("*/analysis.json"))[-limit_issues:]:
        gaps += [g["gap"] for g in json.loads(f.read_text())["research_gaps"]]
    return gaps


def publish(cfg: dict, end: date, items: list[Item], a: dict, sp: dict | None) -> Path:
    title, site = cfg["newsletter"]["title"], cfg["newsletter"]["site_url"].rstrip("/")
    d = end.isoformat()
    week_label = f"week ending {end:%B %-d, %Y}"
    issue_url = f"{site}/issues/{d}" if site else ""

    issue_md = newsletter.render_issue(a, items, title, week_label, d, sp)
    (DOCS / "issues").mkdir(parents=True, exist_ok=True)
    (DOCS / "issues" / f"{d}.md").write_text(issue_md)
    (DOCS / "social").mkdir(exist_ok=True)
    (DOCS / "social" / f"{d}.md").write_text(newsletter.render_social(a, issue_url))

    # The Apps Script sender reads these two files every week.
    html = newsletter.render_email_html(issue_md, title, issue_url, cfg["newsletter"].get("asset_base_url", ""))
    (DOCS / "latest.html").write_text(html)
    (DOCS / "latest.json").write_text(json.dumps(
        {"date": d, "subject": f"{title}: {a['headline']}", "url": issue_url}, indent=2))

    issues = []
    for f in sorted((DOCS / "issues").glob("*.md"), reverse=True):
        head = f.read_text().split("\n", 3)[1]
        issues.append((f.stem, head.removeprefix("title: ").strip('"')))
    (DOCS / "index.md").write_text(newsletter.render_index(title, issues))
    return DOCS / "issues" / f"{d}.md"


def main() -> None:
    p = argparse.ArgumentParser(prog="biomed-ai-watch")
    p.add_argument("command", choices=["run", "collect"], help="run = full weekly pipeline; collect = fetch only")
    p.add_argument("--end", type=date.fromisoformat, help="last day of the window (default: today)")
    p.add_argument("--config", type=Path)
    p.add_argument("--topic", help="spotlight topic for this issue (default: next in config rotation)")
    p.add_argument("--no-spotlight", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    start, end = week_window(cfg, args.end)
    out = DATA / end.isoformat()
    out.mkdir(parents=True, exist_ok=True)

    items = collect(cfg, start, end)
    (out / "items.json").write_text(json.dumps([i.to_dict() for i in items], indent=1))
    log.info("collected %d items for %s..%s", len(items), start, end)
    if args.command == "collect":
        return

    sp = None
    if not args.no_spotlight:
        try:
            sp = spotlight.build(cfg, end, DOCS / "issues" / "assets", args.topic)
            (out / "spotlight.json").write_text(json.dumps(sp, indent=1))
        except Exception:  # the issue still goes out without a spotlight
            log.exception("spotlight failed")

    a = analysis.analyze(items, past_gaps(), f"{start} to {end}", cfg["llm"],
                         spotlight_md=sp["markdown"] if sp else "")
    (out / "analysis.json").write_text(json.dumps(a, indent=1))
    log.info("published %s", publish(cfg, end, items, a, sp))


if __name__ == "__main__":
    main()
