# BioMed AI Watch

A weekly, fully automated newsletter on AI in medicine: research, awarded grants, pharma and device
updates, a deep-dive **Topic Spotlight**, and a systematic search for **novel research gaps**.
It's written by Claude from public data and emailed to subscribers from your own Gmail.

## What each issue contains

| Section | Sources | How |
|---|---|---|
| **Topic spotlight** (rotates weekly) | PubMed counts + live web search | Claude expands the topic into synonyms / MeSH terms / subareas, we chart a 10-year publication trend and a **gap map** (subarea × evidence stage & population), then Claude researches the web and ranks 3–5 novel gaps with suggested studies |
| AI medical research | PubMed, arXiv, medRxiv | themes + must-read papers |
| Grants awarded | NIH RePORTER, NSF Awards | new AI-in-health awards, reported once |
| Pharma & medical products | openFDA 510(k), FDA press releases, Fierce Biotech, STAT | AI device clearances, approvals, industry news |
| Research gaps | all of the above + previous issues | novel gaps, marked when recurring |
| Social drafts | — | LinkedIn post, X thread, Bluesky post for review |

## How it fits together

```
 GitHub Actions (Sun 14:00 UTC)                      Google Apps Script (your account)
 ┌────────────────────────────────────┐             ┌───────────────────────────────────────┐
 │ collect → spotlight → analyse      │  latest.*   │ Mon 08:00 trigger: sendWeekly()        │
 │ writes docs/issues/<date>.md       │ ──────────► │  reads latest.json / latest.html       │
 │        docs/latest.html / .json    │  (raw URL)  │  sends via Gmail to active subscribers │
 │        docs/social/<date>.md       │             │  archives a copy in Drive              │
 │ commits → GitHub Pages blog        │             │                                       │
 └────────────────────────────────────┘             │ doPost  ← subscribe form on dkundnani.bio
                                                    │ doGet   ← confirm / unsubscribe links   │
                                                    │ Google Sheet in Drive = subscriber list │
                                                    └───────────────────────────────────────┘
```

Why this model: no mailing-list vendor, no server, and no Gmail credentials stored in GitHub. Subscribers
live in a Sheet you own, and mail goes out from your own Gmail with double opt-in and one-click unsubscribe.
**Limit:** a consumer Gmail account can email about 100 recipients a day from Apps Script (Workspace
accounts get 1,500). The sender resumes the next day if it runs out of quota. Past a few hundred
subscribers, move sending to Buttondown, Mailchimp or Amazon SES. The Sheet exports as CSV.

## Setup

### 1. Repository and weekly generation
1. Create `DKundnani/biomed-ai-watch` on GitHub and push this repo.
2. **Settings → Secrets → Actions**: add `ANTHROPIC_API_KEY` (and optionally `NCBI_API_KEY`, `NCBI_EMAIL`).
3. **Settings → Pages**: deploy from branch `main`, folder `/docs`. With your custom domain, the blog
   is served at `https://dkundnani.bio/biomed-ai-watch/`.
4. **Actions → Weekly issue → Run workflow** to produce the first issue. You can pass an end date.

Local run:
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env    # add your key, then: export $(cat .env | xargs)
biomed-ai-watch collect                          # fetch only, no Claude calls
biomed-ai-watch run --topic "Electronic health records"
pytest
```

### 2. Subscriptions and sending (Google Drive + Gmail)
1. Open <https://script.google.com> → **New project**, named "BioMed AI Watch".
2. Paste `apps_script/Code.gs` into `Code.gs`. Under **Project settings**, tick "Show appsscript.json"
   and paste `apps_script/appsscript.json`.
3. Run **`setup`** once and approve the permissions. It creates a `BioMed AI Watch` folder in Drive with the
   subscriber Sheet and an `Archive` folder, and installs the Monday 08:00 send trigger.
4. **Deploy → New deployment → Web app**, execute as **Me**, access **Anyone**. Copy the `/exec` URL into
   `CONFIG.WEB_APP_URL` in `Code.gs`, then **Deploy → Manage deployments → Edit → New version**.
5. Put the same URL in `website/subscribe-snippet.html` and add the snippet to your site.

### 3. Test with your Gmail
1. Run **`sendTestToMe`**: the latest issue arrives in your inbox with a `[TEST]` subject.
2. Subscribe your Gmail through the website form. You should get a confirmation email, the Sheet row
   should go `pending` → `active` when you click the link, and the unsubscribe link should set it to `unsubscribed`.
3. Run **`sendWeekly`** manually to see exactly what subscribers receive.

## Configuration
Everything lives in `config.yaml`: search queries, lookback windows, RSS feeds, the spotlight topic rotation,
model, and effort. The spotlight follows the topic list by ISO week number. Override it with `--topic`.

## Cost
Each issue makes three Claude calls (`claude-opus-5-5`): term expansion, spotlight web research (up to 15
searches and 10 fetches), and the main synthesis. Expect a few dollars per issue. The main levers are
`llm.effort` and `max_per_source` in `config.yaml`.

## Caveats
- Every claim links to its source, and IDs the model cites are checked against collected records. Still,
  review the issue (or at least the social drafts) before it goes out. The Action commits on Sunday and email goes on Monday,
  so you have a window to edit `docs/latest.html` or pause the trigger.
- Gap-map facets match on keywords and are approximate. Read them as signals, not as a systematic review.
- Preprints (arXiv, medRxiv) are not peer reviewed. The newsletter says so.
