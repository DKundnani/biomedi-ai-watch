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
 this repo: GitHub Action (Sun 14:00 UTC)           dkundnani.bio (DKundnani/dkundnani.github.io)
 ┌────────────────────────────────────┐             ┌────────────────────────────────────────────┐
 │ collect → spotlight → analyse      │   commits   │ newsletter.html       subscribe + archive   │
 │ archives issues/, social/, data/   │ ──────────► │ newsletter/<date>.html issue page          │
 └────────────────────────────────────┘             │ newsletter/latest.html / latest.json       │
                                                    └──────────────────┬─────────────────────────┘
                                                                       │ read Monday 08:00
                                    ┌──────────────────────────────────▼─────────────────────────┐
                                    │ the site's existing Apps Script mail relay                 │
                                    │  scripts/mail-relay.gs + scripts/newsletter.gs             │
                                    │  sign-ups pass the relay's spam gate, then double opt-in   │
                                    │  subscribers in a Google Sheet in Drive; sends via Gmail   │
                                    │  confirm / unsubscribe links; Drive archive of each issue  │
                                    └────────────────────────────────────────────────────────────┘
```

Subscriptions reuse the contact form's relay, so there is one Apps Script deployment, one URL, and one
spam gate (honeypot, signed page stamp, optional captcha, hourly cap). Gmail from Apps Script allows about
100 recipients a day on a personal account. The sender carries any leftover subscribers to the next run, and
keeps a little headroom for contact-form mail. Past a few hundred subscribers, move sending to a mailing
service. The Sheet exports as CSV.

## Setup

### 1. This repo
1. **Settings → Secrets → Actions**: add `ANTHROPIC_API_KEY` (and optionally `NCBI_API_KEY`, `NCBI_EMAIL`).
2. Let the Action push to the website: create a key pair with `ssh-keygen -t ed25519 -f site_key -N ""`.
   Add `site_key.pub` as a **deploy key with write access** on `DKundnani/dkundnani.github.io`, and
   `site_key` as the secret `SITE_DEPLOY_KEY` here. Then delete both files.
3. **Actions → Weekly issue → Run workflow** for the first issue. You can set a topic and end date.

Local run (writes into `../dkundnani.github.io`, which you then review and push):
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
export ANTHROPIC_API_KEY=...
biomed-ai-watch collect                          # fetch only, no Claude calls
biomed-ai-watch run --topic "Electronic health records"
pytest
```

### 2. Subscriptions (in the website's Apps Script project)
1. Open the existing mail-relay project at <https://script.google.com>. Add a file `newsletter.gs` with the
   contents of `scripts/newsletter.gs` from the website repo, and replace `Code.gs` with the updated
   `scripts/mail-relay.gs`.
2. Run **`newsletterSetup`** once and approve the new Drive and Sheets permissions. It creates a
   `BioMed AI Watch` folder with the subscriber Sheet and an `Archive` folder, and installs the Monday 08:00 trigger.
3. **Deploy → Manage deployments → edit the existing deployment → Version: New version**. The URL stays
   the same, so the forms on the site keep working.

### 3. Test with your Gmail
1. On dkundnani.bio/newsletter.html, subscribe your Gmail. A confirmation email should arrive, and the
   Sheet row should go from `pending` to `active` when you click its link.
2. After the first issue is published, run **`sendTestToMe`** for a `[TEST]` copy, then **`sendWeekly`** to send it for real.
3. Click **Unsubscribe** in the issue. The row should change to `unsubscribed`.

## Configuration
Everything lives in `config.yaml`: search queries, lookback windows, RSS feeds, the spotlight topic rotation,
model, and effort. The spotlight follows the topic list by ISO week number. Override it with `--topic`.

## Cost
Each issue makes three Claude calls (`claude-opus-5-5`): term expansion, spotlight web research (up to 15
searches and 10 fetches), and the main synthesis. Expect a few dollars per issue. The main levers are
`llm.effort` and `max_per_source` in `config.yaml`.

## Caveats
- Every claim links to its source, and IDs the model cites are checked against collected records. Still,
  review the issue (or at least the social drafts) before it goes out. The Action publishes on Sunday and email goes out on Monday,
  so you have a window to edit `newsletter/latest.html` on the site or pause the trigger.
- Gap-map facets match on keywords and are approximate. Read them as signals, not as a systematic review.
- Preprints (arXiv, medRxiv) are not peer reviewed. The newsletter says so.
