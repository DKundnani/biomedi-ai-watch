"""biomed-ai-watch command line: collect -> analyse -> publish."""
from __future__ import annotations

import argparse
import json
import logging
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import analysis, charts, newsletter, site, spotlight
from .config import ROOT, load_config, week_window
from .models import Item
from .sources import grants, papers, products

log = logging.getLogger("biomed_ai_watch")
DATA, ISSUES, SOCIAL = ROOT / "data", ROOT / "issues", ROOT / "social"


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


def publish(cfg: dict, end: date, items: list[Item], a: dict, sp: dict | None, site_dir: Path,
            chart_dir: Path) -> Path:
    nl = cfg["newsletter"]
    title, d = nl["title"], end.isoformat()
    week_label = f"week ending {end:%B %-d, %Y}"
    issue_url = f"{nl['site_url'].rstrip('/')}/{d}.html"

    # The chart picker chooses this week's graphs from the data and draws them as slides.
    slides = charts.build(items, a, sp, cfg["llm"], chart_dir, d)

    # Archive copies in this repo.
    issue_md = newsletter.render_issue(a, items, title, week_label, d, sp, slides)
    ISSUES.mkdir(exist_ok=True)
    SOCIAL.mkdir(exist_ok=True)
    (ISSUES / f"{d}.md").write_text(issue_md)
    (SOCIAL / f"{d}.md").write_text(newsletter.render_social(a, issue_url))

    # The website: issue page, slide images, the newsletter home, and the files the Monday sender reads.
    cover = next((s["file"] for s in slides if s["section"] == "spotlight"), slides[0]["file"] if slides else None)
    entry = {"date": d, "title": a["headline"], "subtitle": a.get("subtitle", ""),
             "topic": sp["topic"] if sp else "", "cover": cover,
             "read_min": max(1, round(len(issue_md.split()) / 230)), "description": " ".join(a["tldr"])[:300]}
    issues = site.save_index(site_dir, entry)
    page = site.write_issue_page(site_dir, entry, issue_md, [chart_dir / s["file"] for s in slides], issues)
    site.refresh_neighbours(site_dir, issues)
    site.update_index_page(site_dir, issues)
    email = newsletter.render_email_html(issue_md, title, issue_url, nl["asset_base_url"])
    site.write_latest(site_dir, d, f"{title}: {a['headline']}", issue_url, email)
    return page


def main() -> None:
    p = argparse.ArgumentParser(prog="biomed-ai-watch")
    p.add_argument("command", choices=["run", "collect"], help="run = full weekly pipeline; collect = fetch only")
    p.add_argument("--end", type=date.fromisoformat, help="last day of the window (default: today)")
    p.add_argument("--config", type=Path)
    p.add_argument("--topic", help="spotlight topic for this issue (default: next in config rotation)")
    p.add_argument("--no-spotlight", action="store_true")
    p.add_argument("--site-dir", type=Path, help="checkout of the website repo (default: newsletter.site_dir in config)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    cfg = load_config(args.config)
    start, end = week_window(cfg, args.end)
    out = DATA / end.isoformat()
    out.mkdir(parents=True, exist_ok=True)

    items = collect(cfg, start, end)
    (out / "items.json").write_text(json.dumps([i.to_dict() for i in items], indent=1))
    log.info("collected %d items for %s..%s", len(items), start, end)
    if args.command == "collect":
        return

    chart_dir = Path(tempfile.mkdtemp(prefix="bmaw-charts-"))
    sp = None
    if not args.no_spotlight:
        try:
            sp = spotlight.build(cfg, end, args.topic)
            (out / "spotlight.json").write_text(json.dumps(sp, indent=1))
        except Exception:  # the issue still goes out without a spotlight
            log.exception("spotlight failed")

    a = analysis.analyze(items, past_gaps(), f"{start} to {end}", cfg["llm"],
                         spotlight_md=sp["markdown"] if sp else "")
    (out / "analysis.json").write_text(json.dumps(a, indent=1))
    site_dir = (args.site_dir or ROOT / cfg["newsletter"]["site_dir"]).resolve()
    log.info("published %s", publish(cfg, end, items, a, sp, site_dir, chart_dir))


if __name__ == "__main__":
    main()
