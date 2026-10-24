"""Publish an issue into the dkundnani.bio website repo (static HTML, GitHub Pages).

The website holds the page designs (newsletter.html, newsletter/_template.html, css/newsletter.css);
this module fills them in. newsletter/issues.json on the site is the index every page is built from.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import quote

import markdown

SITE = "https://dkundnani.bio"
MARKERS = {"latest": ("<!-- latest:start -->", "<!-- latest:end -->"),
           "issues": ("<!-- issues:start -->", "<!-- issues:end -->"),
           "topics": ("<!-- topics:start -->", "<!-- topics:end -->")}
CTA = '''<div class="issue-cta">
  <p>Get BioMed AI Watch in your inbox every Monday.</p>
  <a class="btn btn--primary" href="../newsletter.html#subscribe">Subscribe, free</a>
  <a class="btn btn--ghost" href="#share">Share this issue</a>
</div>'''


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _body_html(issue_md: str) -> str:
    """Issue markdown without front matter and the title, deck and stats lines the page header shows."""
    body = issue_md.split("---", 2)[2] if issue_md.startswith("---") else issue_md
    body = re.sub(r"^\s*# .*\n+## .*\n+(#### .*\n+)?", "", body, count=1)
    return markdown.markdown(body, extensions=["sane_lists"])


def _with_toc(body: str) -> tuple[str, str]:
    """Give each h2 an id, list them in a contents box, and put a subscribe prompt before the second half."""
    heads = []

    def add_id(m):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        heads.append((_slug(text), text))
        return f'<h2 id="{heads[-1][0]}">{m.group(1)}</h2>'

    body = re.sub(r"<h2>(.*?)</h2>", add_id, body)
    if len(heads) >= 3:  # mid-issue prompt, like a Substack subscribe widget
        anchor = f'<h2 id="{heads[len(heads) // 2][0]}">'
        body = body.replace(anchor, CTA + "\n" + anchor, 1)
    toc = ""
    if heads:
        toc = ('        <nav class="issue-toc" aria-label="In this issue"><strong>In this issue</strong><ol>'
               + "".join(f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t in heads) + "</ol></nav>")
    return body, toc


def _share(url: str, title: str) -> str:
    u, t = quote(url, safe=""), quote(title, safe="")
    links = [("LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={u}", "i-linkedin"),
             ("X", f"https://twitter.com/intent/tweet?url={u}&text={t}", "i-x"),
             ("Bluesky", f"https://bsky.app/intent/compose?text={t}%20{u}", "i-send"),
             ("Email", f"mailto:?subject={t}&body={u}", "i-mail")]
    out = [f'<a href="{href}" target="_blank" rel="noopener"><svg class="icon" aria-hidden="true"><use href="#{icon}"/></svg> {name}</a>'
           for name, href, icon in links]
    out.append(f'<button type="button" data-copy="{html.escape(url)}"><svg class="icon" aria-hidden="true"><use href="#i-link"/></svg> Copy link</button>')
    return '<span id="share"></span>' + "".join(out)


def _nav(prev: dict | None, nxt: dict | None) -> str:
    cell = lambda e, cls, label: (f'<a class="{cls}" href="{e["date"]}.html"><small>{label}</small>{html.escape(e["title"])}</a>'
                                  if e else "")
    return f'        <nav class="issue-nav" aria-label="More issues">{cell(prev, "prev", "Previous issue")}{cell(nxt, "next", "Next issue")}</nav>'


def _tag(e: dict) -> str:
    return "Weekly issue" + (f" &middot; Spotlight: {html.escape(e['topic'])}" if e.get("topic") else "")


def _long(d: str) -> str:
    return f"{date.fromisoformat(d):%B %-d, %Y}"


def _cover_url(e: dict) -> str:
    return f"{SITE}/newsletter/assets/{e['cover']}" if e.get("cover") else f"{SITE}/images/web/og-card.jpg"


# ---------- index of issues ----------

def load_index(site: Path) -> list[dict]:
    f = site / "newsletter" / "issues.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_index(site: Path, entry: dict) -> list[dict]:
    """Insert or replace this issue's entry; newest first."""
    issues = [e for e in load_index(site) if e["date"] != entry["date"]] + [entry]
    issues.sort(key=lambda e: e["date"], reverse=True)
    (site / "newsletter" / "issues.json").write_text(json.dumps(issues, indent=1))
    return issues


# ---------- pages ----------

def write_issue_page(site: Path, entry: dict, issue_md: str, charts: list[Path], issues: list[dict]) -> Path:
    """entry: date, title, subtitle, topic, cover, read_min, description."""
    out = site / "newsletter"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    for png in charts:
        shutil.copy2(png, out / "assets" / png.name)
    d = entry["date"]
    url = f"{SITE}/newsletter/{d}.html"
    body, toc = _with_toc(_body_html(issue_md))
    k = next(i for i, e in enumerate(issues) if e["date"] == d)
    nxt, prev = (issues[k - 1] if k > 0 else None), (issues[k + 1] if k + 1 < len(issues) else None)
    values = {"TITLE": html.escape(entry["title"]), "DESCRIPTION": html.escape(entry["description"], quote=True),
              "URL": url, "COVER_URL": _cover_url(entry), "TAG": _tag(entry),
              "SUBTITLE": html.escape(entry.get("subtitle", "")), "DATE": d, "DATE_LONG": _long(d),
              "READ": str(entry.get("read_min", 5)), "SHARE": _share(url, entry["title"]),
              "TOC": toc, "NAV": _nav(prev, nxt), "WEEK": f"week ending {_long(d)}", "CONTENT": body}
    page = (out / "_template.html").read_text()
    for key, val in values.items():
        page = page.replace("{{" + key + "}}", val)
    (out / f"{d}.html").write_text(page)
    return out / f"{d}.html"


def refresh_neighbours(site: Path, issues: list[dict]) -> None:
    """Point the previous issue's 'Next issue' link at the new one."""
    for k, e in enumerate(issues[1:2], 1):
        page = site / "newsletter" / f"{e['date']}.html"
        if not page.exists():
            continue
        s = page.read_text()
        nav = _nav(issues[k + 1] if k + 1 < len(issues) else None, issues[k - 1])
        page.write_text(re.sub(r'        <nav class="issue-nav".*?</nav>', lambda _: nav, s, count=1, flags=re.S))


def write_latest(site: Path, d: str, subject: str, url: str, email_html: str) -> None:
    """The two files the Apps Script sender reads every Monday."""
    out = site / "newsletter"
    (out / "latest.html").write_text(email_html)
    (out / "latest.json").write_text(json.dumps({"date": d, "subject": subject, "url": url}, indent=2))


def _card(e: dict) -> str:
    img = (f'<div class="post__media"><img src="newsletter/assets/{e["cover"]}" alt="" loading="lazy"></div>'
           if e.get("cover") else "")
    topic = f'<span class="post__topic">{html.escape(e["topic"])}</span>' if e.get("topic") else ""
    return (f'            <li><a class="post" href="newsletter/{e["date"]}.html">{img}'
            f'<div class="post__meta">{topic}<span>{_long(e["date"])}</span></div>'
            f'<h3>{html.escape(e["title"])}</h3><p>{html.escape(e.get("subtitle", ""))}</p></a></li>')


def update_index_page(site: Path, issues: list[dict]) -> None:
    """Rewrite the latest-issue hero, the issue grid and the spotlight list on newsletter.html."""
    blocks = {"latest": "", "issues": '          <p class="nl-empty">Earlier issues will appear here.</p>',
              "topics": ""}
    if issues:
        e = issues[0]
        img = f'<div class="nl-latest__media"><img src="newsletter/assets/{e["cover"]}" alt=""></div>' if e.get("cover") else ""
        blocks["latest"] = (
            f'          <a class="nl-latest" href="newsletter/{e["date"]}.html">{img}<div class="nl-latest__text">'
            f'<div class="post__meta"><span class="post__topic">Latest issue</span><span>{_long(e["date"])}</span></div>'
            f'<h2>{html.escape(e["title"])}</h2><p>{html.escape(e.get("subtitle", ""))}</p>'
            f'<span class="post__more">Read the latest <svg class="icon" aria-hidden="true"><use href="#i-right"/></svg></span>'
            f'</div></a>')
        if len(issues) > 1:
            blocks["issues"] = '          <ul class="nl-grid">\n' + "\n".join(_card(x) for x in issues[1:]) + "\n          </ul>"
        spot = [x for x in issues if x.get("topic")][:6]
        blocks["topics"] = "\n".join(
            f'            <li><a href="newsletter/{x["date"]}.html"><span>{html.escape(x["topic"])}'
            f'<small>{_long(x["date"])}</small></span>'
            + (f'<img src="newsletter/assets/{x["cover"]}" alt="" loading="lazy">' if x.get("cover") else "")
            + "</a></li>" for x in spot)
    page = site / "newsletter.html"
    s = page.read_text()
    for key, (start, end) in MARKERS.items():
        if start in s:
            s = s[: s.index(start)] + f"{start}\n{blocks[key]}\n{end}" + s[s.index(end) + len(end):]
    page.write_text(s)
