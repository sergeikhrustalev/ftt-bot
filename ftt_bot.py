import argparse
import hashlib
import json
import os
import re
import socket
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import trafilatura

socket.setdefaulttimeout(15)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = os.environ.get("CHANNEL", "@bozhespartakhranii")

SOURCES = [
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml"},
    {"name": "РИА", "url": "https://ria.ru/export/rss2/archive/index.xml"},
    {"name": "Лента", "url": "https://lenta.ru/rss/news"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

TEXT_LIMIT = 3500
QUEUE_FILE = "queue.json"
POSTED_FILE = "posted.json"
MAX_QUEUE_SIZE = 200
DEFAULT_CUTOFF_HOURS = 4

FLAGS = [
    ("🇷🇺", ["россия", "российск", "москва", "кремль", "путин", "медведев"]),
    ("🇺🇸", ["сша", "американ", "вашингтон", "байден", "трамп", "белый дом"]),
    ("🇨🇳", ["китай", "китайск", "пекин", "си цзиньпин"]),
    ("🇺🇦", ["украина", "украинск", "киев", "зеленский"]),
    ("🇩🇪", ["германия", "немецк", "берлин"]),
    ("🇬🇧", ["великобритания", "британ", "лондон"]),
    ("🇫🇷", ["франция", "французск", "париж", "макрон"]),
    ("🇮🇱", ["израиль", "израильск", "тель-авив"]),
    ("🇮🇷", ["иран", "иранск", "тегеран"]),
    ("🇹🇷", ["турция", "турецк", "анкара", "эрдоган"]),
    ("🇯🇵", ["япония", "японск", "токио"]),
    ("🇰🇷", ["южная корея", "корейск", "сеул"]),
    ("🇰🇵", ["северная корея", "пхеньян", "ким чен"]),
    ("🇸🇾", ["сирия", "сирийск", "дамаск"]),
    ("🇵🇸", ["палестина", "палестинск", "газа", "хамас"]),
    ("🇸🇦", ["саудовск", "эр-рияд"]),
    ("🇮🇳", ["индия", "индийск", "нью-дели", "моди"]),
    ("🇧🇷", ["бразилия", "бразильск"]),
    ("🇦🇺", ["австралия", "австралийск"]),
    ("🇨🇦", ["канада", "канадск", "оттава"]),
    ("🌍", []),
]


def detect_flag(text):
    text_lower = text.lower()
    for flag, keywords in FLAGS:
        if keywords and any(kw in text_lower for kw in keywords):
            return flag
    return "🌍"


def fetch_article_text(url):
    try:
        response = requests.get(url, timeout=12, headers=HEADERS)
        if not response.ok:
            return ""
        text = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
        )
        if not text:
            return ""
        chunk = text[:TEXT_LIMIT]
        if len(text) > TEXT_LIMIT:
            dot = chunk.rfind(".")
            chunk = chunk[: dot + 1] if dot > TEXT_LIMIT // 2 else chunk.rstrip() + "..."
        return chunk
    except Exception as exc:
        print(f"Text fetch error: {exc}")
        return ""


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_post(article):
    pub_dt = parse_dt(article.get("pub_dt"))
    msk = timezone(timedelta(hours=3))
    time_str = pub_dt.astimezone(msk).strftime("%H:%M") if pub_dt else ""
    title = article.get("title", "")
    body = article.get("body", "")
    flag = detect_flag(title + " " + body)

    text = f"{flag} <b>{escape_html(title)}</b>"
    if body:
        text += f"\n\n{escape_html(body)}"
    text += f"\n\n📰 {article.get('source', 'Новости')}"
    if time_str:
        text += f" | 🕐 {time_str} МСК"
    return text


def send_telegram(text):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    if not response.ok:
        print(f"Telegram error: {response.text}")
    return response.ok


def get_article_id(url):
    return hashlib.md5(url.encode()).hexdigest()


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as file_obj:
        return json.load(file_obj)


def save_json_file(path, payload):
    with open(path, "w") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)


def load_posted():
    return set(load_json_file(POSTED_FILE, []))


def save_posted(posted):
    save_json_file(POSTED_FILE, sorted(posted))


def load_queue():
    queue = load_json_file(QUEUE_FILE, [])
    queue.sort(key=lambda item: item.get("pub_dt", ""))
    return queue


def save_queue(queue):
    save_json_file(QUEUE_FILE, queue[:MAX_QUEUE_SIZE])


def normalize_title(title):
    return re.sub(r"\W+", "", title.lower())[:80]


def fetch_feed(url):
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return feedparser.parse(response.content)


def collect_articles(cutoff_hours=DEFAULT_CUTOFF_HOURS):
    posted = load_posted()
    queue = load_queue()
    queued_ids = {item["id"] for item in queue}
    queued_titles = {normalize_title(item["title"]) for item in queue}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cutoff_hours)
    collected = []

    for source in SOURCES:
        try:
            feed = fetch_feed(source["url"])
            if feed.bozo and not feed.entries:
                print(f"Feed error {source['name']}: {feed.bozo_exception}")
                continue

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                if not title or not url:
                    continue

                article_id = get_article_id(url)
                title_key = normalize_title(title)
                if article_id in posted or article_id in queued_ids or title_key in queued_titles:
                    continue

                pub = entry.get("published_parsed")
                pub_dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else now
                if pub_dt < cutoff:
                    continue

                collected.append(
                    {
                        "id": article_id,
                        "title": title,
                        "url": url,
                        "source": source["name"],
                        "pub_dt": pub_dt.isoformat(),
                    }
                )
                queued_ids.add(article_id)
                queued_titles.add(title_key)
        except Exception as exc:
            print(f"Error fetching {source['name']}: {exc}")

    collected.sort(key=lambda item: item["pub_dt"])
    queue.extend(collected)
    queue.sort(key=lambda item: item["pub_dt"])
    queue = queue[:MAX_QUEUE_SIZE]
    save_queue(queue)

    print(
        f"Collect done. Added {len(collected)} items. "
        f"Queue length: {len(queue)}. Posted total: {len(posted)}."
    )


def send_one():
    posted = load_posted()
    queue = load_queue()

    if not queue:
        print("Queue is empty. Nothing to send.")
        return

    article = queue[0]
    article["body"] = fetch_article_text(article["url"])
    text = format_post(article)

    if not send_telegram(text):
        print(f"Send failed, item left in queue: {article['title']}")
        return

    posted.add(article["id"])
    queue = queue[1:]
    save_posted(posted)
    save_queue(queue)
    print(f"Sent: {article['title']}")
    print(f"Queue left: {len(queue)}. Posted total: {len(posted)}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        nargs="?",
        default="run",
        choices=["run", "collect", "send-one"],
        help="run = collect + send one item, collect = only collect, send-one = only send",
    )
    args = parser.parse_args()

    if args.mode in {"run", "collect"}:
        collect_articles()
    if args.mode in {"run", "send-one"}:
        send_one()


if __name__ == "__main__":
    main()
