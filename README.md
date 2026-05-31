# Reddit-Tool Suite

A cohesive, **ToS-compliant** Python toolkit for a serialized-storytelling
business that publishes on its **own subreddit** and sells a **Patreon that gives
members influence over the story** (plot-direction polls, character naming/fates,
early access + free-form suggestions).

The suite optimizes the whole funnel — **Reddit views → subreddit subscribers →
Patreon members** — and measures it end to end. It is one application with a
shared core; each tool plugs in rather than living as a disconnected script.

> The design is **generic and config-driven**: Patreon tiers/perks are synced
> live from the Patreon API, so it adapts to any creator without code changes.

## The tools

| Stage | Tool | What it does |
|-------|------|--------------|
| **Growth** | `post_scheduler` | Schedule & submit chapters to your home sub at chosen times. |
| | `timing_analyzer` | Derive best posting windows from your post history. |
| | `ab_titles` | Track title/hook variants and score which performed best. |
| | `cross_promo` | Track other subs' self-promo rules/cadence and *warn* you — never auto-posts. |
| | `engagement_monitor` | Surface high-value comments + draft replies for a human to send. |
| **Conversion** | `cta_links` | Generate trackable UTM links to your Patreon + manage CTA snippets. |
| | `attribution` | Match Reddit-sourced clicks to new Patreon members. |
| | `polls` | Member voting: plot/naming polls, free-form suggestions, one vote per member. |
| | `teaser_gen` | Draft FOMO "members chose X" posts (you review & post). |
| **Analytics** | `collectors` | Snapshot Reddit + Patreon metrics over time. |
| | `sentiment` | Score comment sentiment (VADER by default; optional transformer backend). |
| | `funnel` + dashboard | Tie upvotes → clicks → conversions → patrons → MRR in one view. |
| | `alerts` | Flag MRR drops, churn spikes, and dead campaigns. |
| | `export` | Dump funnel + metrics to CSV/JSON for spreadsheets/BI. |

### The web control panel

`redditsuite analytics dashboard` serves a full click-everything web app (and the
click redirect) at `http://127.0.0.1:8000`. No command line needed for daily use:

- **Dashboard** — the funnel (posts → upvotes → clicks → conversions → patrons → MRR), an anomaly banner, Patreon trend, churn & tier mix, a best-posting-times heatmap, A/B title winners, clicks-by-campaign, attribution confidence, and a comment-sentiment strip.
- **Chapters** — a form to schedule chapters and a "post what's due now" button.
- **Patreon Links** — make trackable CTA links and copy the short URL into your posts.
- **Polls** — create member polls, record votes, close them to reveal the winner, and get a teaser draft.
- **Comments** — the high-value reply queue with suggested openers; mark them handled.
- **Tools** — one-click refresh stats, find best posting times, export to CSV/JSON, and manage cross-promo targets.

Windows users can skip the command line entirely — see `QUICKSTART.txt`
(`setup.bat` then `start.bat`).

## Compliance, by design

Reddit and Patreon prohibit spam, vote manipulation and fake engagement. Those
rules are enforced centrally in `core/compliance.py`:

- Posting is limited to **your own content on your own sub**, with minimum
  spacing and a per-day cap.
- **No Reddit vote/award manipulation** — member voting happens only inside our
  own poll system, one vote per member.
- Risky actions (comment replies, cross-posting, teaser posts) are
  **human-in-the-loop**: the tools *draft*, a human approves and sends.
- Click tracking stores a **salted IP hash**, never raw PII.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # fill in Reddit + Patreon credentials
redditsuite db init           # create the SQLite database

# Schedule a chapter, make a tracked CTA link, open a member poll
redditsuite growth schedule --title "Chapter 1" --when 2026-06-01T17:00 --chapter 1
redditsuite conversion cta-create --destination https://patreon.com/<id> --campaign chapter-1
redditsuite conversion poll-create --question "Which door?" -o "Left" -o "Right" --kind plot

# Run the funnel dashboard + click-redirect service
redditsuite analytics dashboard      # http://127.0.0.1:8000

# Check anomalies and export data
redditsuite analytics alerts
redditsuite analytics export --format csv --out ./exports

# Run the background scheduler (posting, metric collection, attribution, alerts)
redditsuite run
```

To try the optional transformer sentiment backend, install `transformers`
yourself and set `SENTIMENT_BACKEND=transformer` in `.env` (it falls back to
VADER if the library is unavailable).

Run `redditsuite --help` (and `redditsuite <group> --help`) to see every command.

## Architecture

```
src/redditsuite/
  cli.py            Typer CLI; groups growth/conversion/analytics + db/run
  core/             config, db, models, repositories, reddit/patreon clients,
                    scheduler, compliance  (every tool imports core only)
  growth/           post_scheduler, timing_analyzer, ab_titles, cross_promo,
                    engagement_monitor
  conversion/       cta_links, attribution, polls, teaser_gen
  analytics/        collectors, sentiment, funnel, dashboard/ (FastAPI)
  services/         utm_redirect (click-logging redirect, shares dashboard app)
migrations/         Alembic migrations (autogenerated from core/models.py)
tests/              pytest suite; all external APIs mocked
```

Each tool optionally exposes `register_cli(group)` and `register_jobs(scheduler)`,
so adding a tool means adding a file — never editing a monolith.

## Database & migrations

`redditsuite db init` creates the schema directly for a quick start. For
evolving the schema over time, use Alembic:

```bash
alembic upgrade head                                   # apply migrations
alembic revision --autogenerate -m "describe change"   # after editing models
```

## Development

```bash
pytest         # all tests, no network access required
ruff check .   # lint
```

Tests mock the Reddit and Patreon clients (the only external seams) and run
against a throwaway SQLite database, so the suite is fast and hermetic.
