# USA JOB HUNTER

Verified U.S. Mathematics teaching jobs for international educators: discovery, verification,
résumé matching, J-1 research and application tracking.

## Run

```powershell
.\run.ps1
```

Open http://127.0.0.1:8000, create your account (first run only), then press **SCAN USA NOW**.

Data lives in `data/` (SQLite by default). For PostgreSQL set
`DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/jobhunter` before starting.

## What is real, and where it comes from

| Source | Tier | Notes |
|---|---|---|
| SchoolSpring API (`api.schoolspring.com`) | 2 – official ATS | Nationwide keyword search. Each detail returns the employer's own posting URL, deadline, salary and the contact the employer entered. |
| Frontline AppliTrack boards (`applitrack.com/<district>/onlineapp`) | 2 – official ATS | 25 district boards seeded; district names were confirmed from each board's title. Add more in **Scan Monitor → Sources**. |
| Official career pages with schema.org `JobPosting` | 1 | Add any district/charter careers URL in Scan Monitor. |
| GovernmentJobs | — | Not scanned: its robots.txt disallows generic crawlers. |

J-1 sponsor database: seeded only with the three **Teacher**-category sponsors read from the U.S.
Department of State BridgeUSA sponsor search on 2026-09-23. Import the full official list via
**J-1 Jobs → Sponsor database → Import State Dept CSV**.

## Accuracy rules enforced in code

- No fabricated data: every job, contact, email, salary and J-1 claim is stored with its source URL,
  source type, verification status and timestamp (`field_evidence`, `job_sources`, `job_verifications`).
- Emails are shown only when the exact address appears on the source; there is no code path that
  builds `firstname.lastname@…` addresses. Manually added emails are fetched and must appear on the page.
- Salutations use a published honorific (Mr./Ms./Dr.) or the full name, never a guess from a first name.
  Only HIGH-confidence, vacancy-linked contacts are auto-recommended; otherwise "Dear Hiring Committee:".
- J-1: a vacancy is "Confirmed J-1" only from its own posting or an official employer page;
  a sponsor existing in the same state is never treated as evidence.
- Duplicates merge into one canonical job with every source URL kept; closed jobs are marked CLOSED,
  never deleted, and linked applications keep their history.
- Demo records are labeled DEMO / FICTIONAL and never appear in live results.
- The scanner respects robots.txt and per-host rate limits and never bypasses logins or CAPTCHAs.
  Every request is logged in the Scan Monitor.

## Schedules

Quick scan every 6 h, full scan daily, contact verification daily, J-1 check every 3 days and the
closed-job check daily. They run in-process while the app is running; edit them in Settings.
Manual buttons: SCAN USA NOW, VERIFY JOBS, VERIFY CONTACTS, CHECK J-1 STATUS.

## Optional AI extraction

`JH_LLM=1` with Anthropic credentials enables `services/llm_extract.py` (Claude Opus 5, structured output,
server-side refusal fallback). It reads only fetched source text, and it discards any field whose
supporting quote is not found verbatim in that source.

## Layout

```
backend/app/
  main.py, models.py, db.py, auth.py, seed.py, serializers.py
  routers/   jobs.py, crm.py, profile.py, admin.py
  services/  scanner.py, ingest.py, matching.py, contacts.py, j1.py, verification.py,
             resume_parser.py, generators.py, exports.py, alerts.py, scheduler.py, http.py
             connectors/ schoolspring.py, applitrack.py, jsonld.py
frontend/    index.html, styles.css, app.js   (served by FastAPI; no build step)
```

The frontend is plain JS because Node.js isn't installed on this machine. The REST API is
framework-agnostic, so a Next.js frontend can replace `frontend/` later without backend changes.

## Online version (sniperteacherjob.vercel.app)

- **Website** (Vercel): `api/index.py` serves the same app. Sign in with the same account as on your computer.
- **Scans** (GitHub Actions, `.github/workflows/scan.yml`): every 4 hours a quick national scan, plus a daily closed-posting /
  contact / engineering check. After each scan:
  1. new open vacancies without a usable principal email get an **AI lookup** (Claude + web search). An email is saved only
     when the app itself re-reads it on the school's / district's official website (`backend/app/services/ai_contacts.py`);
  2. application emails are prepared in the **Outbox** (nothing is sent to a school until you approve it on the website);
  3. you get an email at `JH_NOTIFY_EMAIL` listing new openings and the emails waiting for approval.
- **Database**: Neon PostgreSQL (Vercel > Storage). `backend/migrate_to_cloud.py` copies your local data once.
- **Settings**: see `.env.example`. Cost caps for the AI finder: `JH_AI_MAX_LOOKUPS_PER_RUN` (default 8),
  `JH_AI_MAX_LOOKUPS_PER_DAY` (default 25).
- Cloud servers block the mail-server mailbox check (port 25), so online the rule is "printed on the official website".
