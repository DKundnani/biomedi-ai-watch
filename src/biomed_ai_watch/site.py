"""Publish an issue into the dkundnani.bio website repo (static HTML, GitHub Pages)."""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

import markdown

START, END = "<!-- issues:start -->", "<!-- issues:end -->"


def _body_html(issue_md: str) -> str:
    """Issue markdown without front matter and the title lines the page template already shows."""
    body = issue_md.split("---", 2)[2] if issue_md.startswith("---") else issue_md
    body = re.sub(r"^\s*# .*\n+## .*\n", "", body, count=1)
    return markdown.markdown(body, extensions=["sane_lists"])


def write_issue_page(site: Path, d: str, title: str, week: str, issue_md: str, description: str,
                     charts: list[Path]) -> Path:
    out = site / "newsletter"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    for png in charts:
        shutil.copy2(png, out / "assets" / png.name)
    page = (out / "_template.html").read_text()
    for key, val in {"TITLE": html.escape(title), "DESCRIPTION": html.escape(description, quote=True),
                     "URL": f"https://dkundnani.bio/newsletter/{d}.html", "WEEK": html.escape(week),
                     "CONTENT": _body_html(issue_md)}.items():
        page = page.replace("{{" + key + "}}", val)
    (out / f"{d}.html").write_text(page)
    return out / f"{d}.html"


def write_latest(site: Path, d: str, subject: str, url: str, email_html: str) -> None:
    """The two files the Apps Script sender reads every Monday."""
    out = site / "newsletter"
    (out / "latest.html").write_text(email_html)
    (out / "latest.json").write_text(json.dumps({"date": d, "subject": subject, "url": url}, indent=2))


def update_archive(site: Path, issues: list[tuple[str, str]]) -> None:
    """issues: [(date, headline)] newest first. Rewrites the list on newsletter.html."""
    page = site / "newsletter.html"
    s = page.read_text()
    items = "\n".join(f'            <li><a href="newsletter/{d}.html"><strong>{d}</strong></a> &middot; {html.escape(h)}</li>'
                      for d, h in issues)
    block = f"{START}\n          <ul>\n{items}\n          </ul>\n{END}"
    page.write_text(s[: s.index(START)] + block + s[s.index(END) + len(END):])
