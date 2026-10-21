"""Render an issue to Markdown (newsletter / blog post) plus social-media drafts."""
from __future__ import annotations

from .models import Item


def _link(i: Item) -> str:
    return f"[{i.title}]({i.url})"


def _refs(ids: list[str], index: dict[str, Item]) -> str:
    return ", ".join(f"[{n}]({index[i].url})" for n, i in enumerate(ids, 1) if i in index)


def _highlights(rows: list[dict], index: dict[str, Item], show_amount: bool = False) -> list[str]:
    out = []
    for h in rows:
        it = index[h["id"]]
        meta = [it.source, it.extra.get("journal") or it.extra.get("institution") or ""]
        if show_amount and it.extra.get("amount_usd"):
            meta.append(f"${int(it.extra['amount_usd']):,}")
        out.append(f"- **{_link(it)}** — _{' · '.join(m for m in meta if m)}_  \n  {h['note']}")
    return out


def render_spotlight(sp: dict) -> list[str]:
    terms = sp["terms"]
    L = [f"## Topic spotlight: {sp['topic']}", "",
         f"_Also searched as: {', '.join(terms['synonyms'])}._", ""]
    captions = {"trend": "Publication trend from PubMed", "gapmap": "Gap map: pale cells are where evidence is thin",
                "chart": "From this week's sources"}
    for png in sp["charts"]:
        kind = png.rsplit("-", 1)[-1].removesuffix(".png")
        L += [f"![{captions.get(kind, sp['topic'])}](assets/{png})", ""]
    return L + [sp["markdown"], ""]


def render_issue(a: dict, items: list[Item], title: str, week_label: str, issue_date: str,
                 spotlight: dict | None = None) -> str:
    index = {i.id: i for i in items}
    counts = {k: sum(i.kind == k for i in items) for k in ("paper", "grant", "product")}
    L = [
        "---", f'title: "{a["headline"]}"', f"date: {issue_date}", "---", "",
        f"# {title} — {week_label}", "", f"## {a['headline']}", "",
        f"_This week we scanned {counts['paper']} papers, {counts['grant']} new grants, "
        f"and {counts['product']} pharma/device updates._", "",
        "### TL;DR", *[f"- {t}" for t in a["tldr"]], "",
    ]
    if spotlight:
        L += render_spotlight(spotlight)
    L += ["## 1. AI medical research", ""]
    for t in a["paper_themes"]:
        refs = _refs(t["ids"], index)
        L += [f"**{t['theme']}.** {t['summary']}" + (f" ({refs})" if refs else ""), ""]
    L += ["### Papers to read", *_highlights(a["top_papers"], index), ""]
    L += ["## 2. Grants awarded this week", "", a["grants_summary"], "",
          *_highlights(a["top_grants"], index, show_amount=True), ""]
    L += ["## 3. Pharma & medical product updates", "", a["products_summary"], "",
          *_highlights(a["top_products"], index), ""]
    L += ["## 4. Research gaps", ""]
    for n, g in enumerate(a["research_gaps"], 1):
        tag = " _(recurring)_" if g["recurring"] else ""
        refs = _refs(g["ids"], index)
        L += [f"**{n}. {g['gap']}**{tag}", "",
              f"- Evidence: {g['evidence']}" + (f" ({refs})" if refs else ""),
              f"- Study that would close it: {g['suggested_study']}", ""]
    L += ["---", "_Generated automatically by BioMed AI Watch from PubMed, arXiv, medRxiv, NIH RePORTER, NSF, "
          "openFDA and public news feeds, synthesised with Claude. Preprints are not peer reviewed. "
          "Verify against the linked sources before acting on anything here._", ""]
    return "\n".join(L)


def render_social(a: dict, issue_url: str) -> str:
    s = a["social"]
    link = f"\n\n{issue_url}" if issue_url else ""
    thread = "\n\n".join(f"{n}/{len(s['x_thread'])} {t}" for n, t in enumerate(s["x_thread"], 1))
    return (f"# Social drafts — {a['headline']}\n\n_Review before posting._\n\n"
            f"## LinkedIn\n\n{s['linkedin_post']}{link}\n\n"
            f"## X / Twitter thread\n\n{thread}{link}\n\n"
            f"## Bluesky\n\n{s['bluesky_post']}{link}\n")


def render_index(title: str, issues: list[tuple[str, str]]) -> str:
    """issues: [(date, headline)] newest first."""
    rows = "\n".join(f"- **{d}** — [{h}](issues/{d}.md)" for d, h in issues)
    return (f"# {title}\n\nWeekly intelligence on AI in medicine: new research, awarded grants, "
            f"pharma & device updates, and the research gaps they reveal.\n\n## Issues\n\n{rows}\n")


def render_email_html(issue_md: str, title: str, issue_url: str, asset_base: str = "") -> str:
    """Self-contained, inline-styled HTML for email clients. {{UNSUBSCRIBE_URL}} is filled per subscriber."""
    import markdown

    body_md = issue_md.split("---", 2)[2] if issue_md.startswith("---") else issue_md
    body = markdown.markdown(body_md, extensions=["sane_lists"])
    if asset_base:  # email clients need absolute image URLs
        body = body.replace('src="assets/', f'src="{asset_base.rstrip("/")}/issues/assets/')
    body = body.replace("<img ", '<img style="max-width:100%;height:auto" ')
    body = (body.replace("<h1>", '<h1 style="font-size:22px;margin:0 0 8px">')
                .replace("<h2>", '<h2 style="font-size:18px;margin:28px 0 8px;color:#0b5c6b">')
                .replace("<h3>", '<h3 style="font-size:15px;margin:20px 0 6px">')
                .replace("<a ", '<a style="color:#0b5c6b" '))
    web = f'<p style="font-size:12px;color:#666"><a href="{issue_url}">Read on the web</a></p>' if issue_url else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="margin:0;background:#f4f6f7">
<div style="max-width:640px;margin:0 auto;padding:24px;background:#fff;font-family:Georgia,serif;font-size:15px;line-height:1.55;color:#1d2327">
{web}{body}
<hr style="border:none;border-top:1px solid #ddd;margin:28px 0">
<p style="font-size:12px;color:#666">You're receiving this because you subscribed to {title}.
<a href="{{{{UNSUBSCRIBE_URL}}}}">Unsubscribe</a>.</p>
</div></body></html>"""
