#!/usr/bin/env python3
# main.py
import os
import json
import logging
from datetime import datetime
from html import escape

import feedparser
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Tell sites we are a browser, to prevent CBC/Globe/NYT from dropping the connection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MyNewsBot/1.0; +https://github.com/YOUR_GITHUB_USERNAME)"
}

# ---------- CONFIG ----------
FEEDS_FILE = "feeds.json"
SENT_FILE = "sent_articles.json"
MAX_PER_FEED = int(os.environ.get("MAX_PER_FEED", "5"))
MAX_SENT_STORE = int(os.environ.get("MAX_SENT_STORE", "1000"))

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
TO_EMAIL = os.environ.get("TO_EMAIL")       # e.g. your_email@example.com
FROM_EMAIL = os.environ.get("FROM_EMAIL")   # must be a verified sender in SendGrid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------- helpers ----------
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

def fetch_new_articles(feeds, sent_set):
    articles = []
    for url in feeds:
        try:
            logging.info(f"Fetching {url}")
            parsed = feedparser.parse(url, request_headers=HEADERS)

            if parsed.bozo and not parsed.entries:
                logging.warning(f"Problem parsing feed: {url}")
                continue

            for entry in parsed.entries[:5]:  # limit per feed
                link = entry.link
                if link not in sent_set:
                    articles.append({
                        "title": entry.title,
                        "link": link,
                        "source": parsed.feed.get("title", url),
                    })

        except Exception as e:
            logging.error(f"Failed to fetch {url}: {e}")
            continue  # skip this feed and move on

    return articles


def build_html(articles):
    if not articles:
        return "<p>No new stories today.</p>"
    date_str = datetime.utcnow().strftime("%B %d, %Y")
    parts = [f"<h2>Top stories — {escape(date_str)} (UTC)</h2>"]
    # group by feed
    feeds = {}
    for a in articles:
        feeds.setdefault(a["feed"], []).append(a)
    for feed_name, items in feeds.items():
        parts.append(f"<h3>{escape(feed_name)}</h3><ul>")
        for it in items:
            parts.append(
                "<li>"
                f"<a href='{escape(it['link'])}'>{escape(it['title'])}</a>"
                + (f" <small>({escape(it['published'])})</small>" if it.get("published") else "")
                + (f"<div>{it['summary']}</div>" if it.get("summary") else "")
                + "</li>"
            )
        parts.append("</ul>")
    return "\n".join(parts)

def send_email(subject, html_body):
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY not set")
    if not TO_EMAIL or not FROM_EMAIL:
        raise RuntimeError("TO_EMAIL and FROM_EMAIL must be set")
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=TO_EMAIL,
        subject=subject,
        html_content=html_body
    )
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    resp = sg.send(message)
    logging.info("SendGrid response: %s %s", resp.status_code, getattr(resp, "body", ""))
    return resp.status_code

# ---------- main ----------
def main():
    feeds = load_json(FEEDS_FILE, [])
    sent = load_json(SENT_FILE, [])
    sent_set = set(sent)

    new_articles = fetch_new_articles(feeds, sent_set)
    if not new_articles:
        logging.info("No new articles to send.")
        return

    html = build_html(new_articles)
    subject = f"Daily digest — {datetime.utcnow().strftime('%B %d, %Y')}"

    try:
        status = send_email(subject, html)
        logging.info("Email send status: %s", status)
    except Exception as e:
        logging.exception("Failed to send email: %s", e)
        raise

    # update sent list (store link)
    for a in new_articles:
        sent.append(a["link"])
    # keep the sent list bounded to avoid unlimited growth
    sent = sent[-MAX_SENT_STORE:]
    save_json(SENT_FILE, sent)
    logging.info("Wrote %s with %d total known articles", SENT_FILE, len(sent))

if __name__ == "__main__":
    main()
