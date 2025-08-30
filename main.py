#!/usr/bin/env python3
# Ethiopia Tender Watcher — free 24/7 alerts via GitHub Actions + Yahoo SMTP

import os, json, time, hashlib, smtplib, logging, random
from pathlib import Path
from typing import List, Dict, Tuple
from email.mime.text import MIMEText
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# -----------------------
# Config and constants
# -----------------------
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "seen.json"
KEYWORDS_FILE = ROOT / "config" / "keywords.txt"

ALERT_TO = os.getenv("ALERT_TO", "hailuworku1@yahoo.com")  # default to your email
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mail.yahoo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")  # set in GitHub Secrets
SMTP_PASS = os.getenv("SMTP_PASS")  # set in GitHub Secrets

# Heartbeat: send a daily status email even if no new tenders
HEARTBEAT_HOUR_UTC = int(os.getenv("HEARTBEAT_HOUR_UTC", "6"))  # 06:00 UTC (morning EAT)
HEARTBEAT_ENABLE = os.getenv("HEARTBEAT_ENABLE", "true").lower() == "true"

# HTTP defaults
HDRS = {"User-Agent": "Mozilla/5.0 (TenderWatcher; +https://github.com/)"}
TIMEOUT = 30
RETRY_MAX = 3
RETRY_BASE_SLEEP = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# -----------------------
# Utilities
# -----------------------
def load_keywords() -> List[str]:
    if KEYWORDS_FILE.exists():
        return [ln.strip().lower() for ln in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # sensible defaults if file missing
    return [
        "software","web","website","mobile","app","android","ios","erp","crm","api",
        "devops","security","cybersecurity","waf","pam","observability","itsm",
        "integration","database","ai","machine learning","cloud","portal","digital","ict"
    ]

KEYWORDS = set(load_keywords())

def relevant_score(text: str) -> int:
    t = (text or "").lower()
    return sum(1 for k in KEYWORDS if k in t)

def uid_hash(title: str, buyer: str, deadline: str, url: str) -> str:
    return hashlib.sha256(f"{title}|{buyer}|{deadline}|{url}".encode("utf-8")).hexdigest()

def load_state() -> Dict[str, float]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state: Dict[str, float]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def http_get(url: str) -> requests.Response:
    last_exc = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            r = requests.get(url, headers=HDRS, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            sleep = RETRY_BASE_SLEEP * attempt + random.random()
            logging.warning(f"GET failed {attempt}/{RETRY_MAX} for {url}: {e} (sleep {sleep:.1f}s)")
            time.sleep(sleep)
    raise last_exc

def send_email(subject: str, html: str):
    if not (SMTP_USER and SMTP_PASS and ALERT_TO):
        logging.error("SMTP creds or ALERT_TO missing; cannot send email.")
        return
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_TO
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, [ALERT_TO], msg.as_string())
    logging.info(f"Email sent to {ALERT_TO}: {subject}")

# -----------------------
# Source parsers
# Keep them defensive and easy to adjust.
# -----------------------
Notice = Dict[str, str]

def fetch_ethiopian_tender_com() -> List[Notice]:
    """
    EthiopianTender.com — adjust selectors as needed.
    This uses a broad anchor scan as a safe default, then narrows by keywords.
    """
    base = "https://www.ethiopiantender.com/"
    try:
        r = http_get(base)
        soup = BeautifulSoup(r.text, "lxml")
        notices = []
        for a in soup.select("a"):
            title = a.get_text(strip=True)
            href = a.get("href")
            if not title or not href:
                continue
            full = urljoin(base, href)
            if relevant_score(title) < 1:
                continue
            notices.append({
                "title": title,
                "buyer": "",
                "deadline": "",
                "url": full,
                "source": "EthiopianTender.com",
            })
        return notices
    except Exception as e:
        logging.warning(f"EthiopianTender.com fetch error: {e}")
        return []

def fetch_globaltenders_et_sw() -> List[Notice]:
    """
    GlobalTenders Ethiopia (software-related page). Adjust path/filters/selectors as needed.
    """
    url = "https://www.globaltenders.com/ethiopia/et-software-tenders"
    try:
        r = http_get(url)
        soup = BeautifulSoup(r.text, "lxml")
        notices = []
        for a in soup.select("a"):
            title = a.get_text(strip=True)
            href = a.get("href")
            if not title or not href:
                continue
            full = urljoin(url, href)
            if relevant_score(title) < 1:
                continue
            notices.append({
                "title": title,
                "buyer": "",
                "deadline": "",
                "url": full,
                "source": "GlobalTenders (ET Software)",
            })
        return notices
    except Exception as e:
        logging.warning(f"GlobalTenders fetch error: {e}")
        return []

SOURCES = [
    fetch_ethiopian_tender_com,
    fetch_globaltenders_et_sw,
    # Add more sources here as functions
]

# -----------------------
# Core run loop
# -----------------------
def run_cycle() -> Tuple[List[Notice], int]:
    state = load_state()
    seen = set(state.keys())
    new_notices: List[Notice] = []
    checked_count = 0

    for fetcher in SOURCES:
        items = []
        try:
            items = fetcher()
        except Exception as e:
            logging.warning(f"Fetcher crashed {fetcher.__name__}: {e}")
        for n in items:
            checked_count += 1
            uid = uid_hash(n.get("title",""), n.get("buyer",""), n.get("deadline",""), n.get("url",""))
            # Basic dedupe
            if uid in seen:
                continue
            # Relevance threshold: at least 1 keyword in title or URL
            text_blob = f"{n.get('title','')} {n.get('url','')}"
            if relevant_score(text_blob) < 1:
                continue
            # Optionally: fetch detail page to extract buyer/deadline here (add per-source detail parsers)
            new_notices.append(n)
            state[uid] = time.time()

    # Keep only recent 90 days in state
    cutoff = time.time() - 90*24*3600
    trimmed = {k:v for k,v in state.items() if v >= cutoff}
    if len(trimmed) != len(state):
        state = trimmed
    save_state(state)
    return new_notices, checked_count

def format_email(notices: List[Notice], checked_count: int) -> Tuple[str, str]:
    if notices:
        subject = f"[ET Tenders] {len(notices)} new software/ICT notices"
        rows = []
        for n in notices:
            title = n.get("title","(no title)")
            buyer = n.get("buyer","")
            dl = n.get("deadline","N/A")
            url = n.get("url","#")
            src = n.get("source","")
            rows.append(
                f"<li><b>{title}</b>"
                + (f" — {buyer}" if buyer else "")
                + f" — deadline: {dl}<br>"
                f"<a href='{url}'>{url}</a> <i>({src})</i></li>"
            )
        html = f"""
        <p>New Ethiopia software/ICT tenders detected (checked {checked_count} items):</p>
        <ul>{''.join(rows)}</ul>
        <p style="color:#888">You can tune keywords in config/keywords.txt</p>
        """
        return subject, html
    else:
        subject = "[ET Tenders] No new software/ICT notices"
        html = f"""
        <p>No new matching tenders in the latest check (scanned {checked_count} items).</p>
        <p style="color:#888">This is a heartbeat. You can tune keywords in config/keywords.txt</p>
        """
        return subject, html

def maybe_send_heartbeat():
    # Send a daily heartbeat at HEARTBEAT_HOUR_UTC if no other email was sent recently
    if not HEARTBEAT_ENABLE:
        return False
    state = load_state()
    last_hb = state.get("_last_heartbeat", 0.0)
    now = time.time()
    t = time.gmtime(now)
    target_today = time.mktime(time.struct_time((
        t.tm_year, t.tm_mon, t.tm_mday, HEARTBEAT_HOUR_UTC, 0, 0,
        t.tm_wday, t.tm_yday, t.tm_isdst
    )))
    # If past the target time and last heartbeat is before today’s target, send one
    if now >= target_today and last_hb < target_today:
        send_email("[ET Tenders] Daily heartbeat", "<p>Watcher is running.</p>")
        state["_last_heartbeat"] = now
        save_state(state)
        return True
    return False

def main():
    new_notices, checked = run_cycle()
    subject, html = format_email(new_notices, checked)
    # Only send the main email if we found new notices; otherwise rely on daily heartbeat
    if new_notices:
        send_email(subject, html)
    else:
        maybe_send_heartbeat()

if __name__ == "__main__":
    main()
