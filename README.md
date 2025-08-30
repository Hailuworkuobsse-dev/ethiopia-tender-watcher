# Ethiopia Tender Watcher (Free, 24/7)

A zero-cost bot that checks Ethiopia-focused tender sources every 15 minutes, filters for software/ICT, deduplicates, and emails alerts.

## How it works
- GitHub Actions runs `main.py` on a 15-minute schedule.
- Parsers fetch tender listings and rank by keywords in `config/keywords.txt`.
- Dedupe keys are stored in `state/seen.json` and committed back for persistence.
- Emails are sent via your SMTP (Yahoo supported).

## Quick start
1. Add repo secrets (Settings → Secrets → Actions):
   - `ALERT_TO` = your email (e.g., hailuworku1@yahoo.com)
   - `SMTP_HOST` = smtp.mail.yahoo.com
   - `SMTP_PORT` = 587
   - `SMTP_USER` = your Yahoo email
   - `SMTP_PASS` = your Yahoo App Password
2. Commit the repository (including `state/seen.json` and `config/keywords.txt`).
3. Enable Actions (if prompted). The job runs within 15 minutes.
4. Tune `config/keywords.txt` to adjust relevance.

## Add more sources
Open `main.py` and add new `fetch_*` functions to `SOURCES`. Keep selectors simple and defensive.

## Notes
- Respect robots.txt and site terms. Prefer official feeds when available.
- Heartbeat email is sent daily at 06:00 UTC to confirm liveness.
