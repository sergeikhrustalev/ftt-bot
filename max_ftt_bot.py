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

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID", "-72873687632407"))

MAX_API = "https://botapi.max.ru"

TOPIC_NEWS_KEYWORDS = (
    "ии",
    "ai",
    "искусствен",
    "нейросет",
    "gpt",
    "llm",
    "openai",
    "anthropic",
    "gemini",
    "генератив",
    "агент",
    "бизнес",
    "компан",
    "корпора",
    "стартап",
    "инвест",
    "выручк",
    "прибыл",
    "рынок",
    "продаж",
    "маркетплейс",
    "e-commerce",
    "ecommerce",
    "ipo",
    "акци",
    "фонд",
    "директор",
    "маркетинг",
    "реклам",
    "бренд",
    "трафик",
    "конверс",
    "клиент",
    "продвиж",
    "аудитори",
    "креатор",
    "инфлюенсер",
    "монетизац",
    "adtech",
    "martech",
)

AI_BUSINESS_TECH_KEYWORDS = (
    "ии",
    "ai",
    "искусствен",
    "нейросет",
    "gpt",
    "llm",
    "openai",
    "anthropic",
    "gemini",
    "генератив",
    "агент",
    "бизнес",
    "инвест",
    "рынок",
    "корпора",
    "выручк",
    "стартап",
    "маркетинг",
    "реклам",
    "бренд",
)

NON_NEWS_URL_PATTERNS = ("/reviews/", "/stories/", "/list/", "/cards/")

SOURCES = [
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml", "no_image": False},
    {"name": "РИА", "url": "https://ria.ru/export/rss2/archive/index.xml", "no_image": False},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/main.xml", "no_image": False},
    {"name": "RT", "url": "https://russian.rt.com/rss", "no_image": False},
    {"name": "Ведомости", "url": "https://www.vedomosti.ru/rss/news", "no_image": False},
    {"name": "Лента", "url": "https://lenta.ru/rss/news", "no_image": True},
    {
        "name": "vc.ru AI",
        "url": "https://vc.ru/rss/tag/ai",
        "no_image": False,
        "priority_boost_minutes": 60,
    },
    {
        "name": "vc.ru Marketing",
        "url": "https://vc.ru/rss/tag/marketing",
        "no_image": False,
        "priority_boost_minutes": 50,
    },
    {
        "name": "vc.ru Business",
        "url": "https://vc.ru/rss/tag/business",
        "no_image": False,
        "priority_boost_minutes": 40,
    },
    {
        "name": "RB.RU",
        "url": "https://rb.ru/feeds/all/",
        "no_image": False,
        "priority_boost_minutes": 75,
        "include_keywords": TOPIC_NEWS_KEYWORDS,
        "exclude_url_patterns": NON_NEWS_URL_PATTERNS,
    },
    {
        "name": "RB.RU Marketing",
        "url": "https://rb.ru/feeds/tag/marketing/",
        "no_image": False,
        "priority_boost_minutes": 90,
        "exclude_url_patterns": NON_NEWS_URL_PATTERNS,
    },
    {
        "name": "CNews",
        "url": "https://www.cnews.ru/inc/rss/news_top.xml",
        "no_image": False,
        "priority_boost_minutes": 45,
        "include_keywords": AI_BUSINESS_TECH_KEYWORDS,
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

TEXT_LIMIT = 500
QUEUE_FILE = "queue_max.json"
POSTED_FILE = "posted.json"
MAX_QUEUE_SIZE = 120
DEFAULT_CUTOFF_HOURS = 2
QUEUE_MAX_AGE_HOURS = 8
MAX_FUTURE_SKEW_HOURS = 6

KNOWN_NOISE_LINES = {
    "мировые 24/7 новости",
    "мировые 247 новости",
    "ria.ru",
    "ria",
    "риа",
    "риа новости",
    "тасс",
    "коммерсантъ",
    "rt",
    "ведомости",
    "лента",
    "лента.ру",
    "rb.ru",
    "russian business",
    "cnews",
    "cnews.ru",
    "vc",
    "vc.ru",
}

BOILERPLATE_FRAGMENTS = (
    "читайте также",
    "поделиться",
    "подписывайтесь",
    "подпишитесь",
    "telegram",
    "телеграм",
)

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

LEADING_NOISE_RE = re.compile(
    r"^\s*(?:(?:мировые\s*24\s*/?\s*7\s*новости|rb\.ru|russian business|cnews(?:\.ru)?|vc(?:\.ru)?|"
    r"ria(?:\.ru)?|риа(?:\s+новости)?|тасс|rt|ведомости|лента(?:\.ру)?)\s*[\-–—|:.,]*)+",
    re.IGNORECASE,
)


def detect_flag(text):
    text_lower = text.lower()
    for flag, keywords in FLAGS:
        if keywords and any(kw in text_lower for kw in keywords):
            return flag
    return "🌍"


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def queue_sort_key(item):
    base_dt = parse_dt(item.get("pub_dt")) or datetime.min.replace(tzinfo=timezone.utc)
    boost_minutes = int(item.get("priority_boost_minutes", 0))
    return base_dt + timedelta(minutes=boost_minutes)


def collapse_spaces(text):
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title):
    return re.sub(r"\W+", "", title.lower())[:80]


def strip_html(text):
    return collapse_spaces(re.sub(r"<[^>]+>", " ", text or ""))


def trim_text(text, limit=TEXT_LIMIT):
    if len(text) <= limit:
        return text
    chunk = text[:limit]
    dot = chunk.rfind(".")
    return chunk[: dot + 1] if dot > limit // 2 else chunk.rstrip() + "..."


def is_source_credit(line):
    cleaned = collapse_spaces(line).strip(" .:-|")
    if not cleaned or len(cleaned) > 60:
        return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё'’.-]+", cleaned)
    if not 1 <= len(words) <= 4:
        return False
    return all(word[:1].isupper() for word in words)


def looks_like_leading_source_sentence(sentence):
    cleaned = collapse_spaces(sentence).strip(" .:-|")
    if not cleaned:
        return False
    if normalize_title(cleaned) in {normalize_title(x) for x in KNOWN_NOISE_LINES}:
        return True
    if not is_source_credit(cleaned):
        return False
    return bool(re.search(r"[A-Za-z]", cleaned))


def strip_leading_noise(text):
    cleaned = collapse_spaces(text)
    if not cleaned:
        return ""

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = LEADING_NOISE_RE.sub("", cleaned).lstrip(" .,:;|-")
        match = re.match(r"^([^.!?\n]{2,60}[.!?])\s+(.*)$", cleaned)
        if match and looks_like_leading_source_sentence(match.group(1)):
            cleaned = match.group(2).lstrip(" .,:;|-")

    return cleaned


def clean_body(text, title="", source=""):
    if not text:
        return ""

    title_norm = normalize_title(title)
    source_norm = normalize_title(source)
    filtered_lines = []

    for raw_line in re.split(r"[\r\n]+", text):
        line = strip_leading_noise(raw_line)
        if not line:
            continue

        line_norm = normalize_title(line)
        line_lower = line.lower().strip(" .:-|")

        if not line_norm:
            continue
        if line_norm == title_norm or line_norm == source_norm:
            continue
        if line_lower in KNOWN_NOISE_LINES:
            continue
        if any(fragment in line_lower for fragment in BOILERPLATE_FRAGMENTS):
            continue
        if is_source_credit(line) and not filtered_lines:
            continue

        filtered_lines.append(line)

    body = strip_leading_noise(" ".join(filtered_lines))
    if not body:
        return ""

    if title and body.lower().startswith(title.lower()):
        body = body[len(title) :].lstrip(" .,:;|-")

    if not body:
        return ""

    return trim_text(body)


def dedupe_articles(items):
    unique = []
    seen_ids = set()
    seen_titles = set()

    for item in sorted(items, key=queue_sort_key, reverse=True):
        article_id = item.get("id")
        title_key = normalize_title(item.get("title", ""))
        if not article_id or article_id in seen_ids or title_key in seen_titles:
            continue
        seen_ids.add(article_id)
        seen_titles.add(title_key)
        unique.append(item)

    return unique


def matches_keywords(text, keywords):
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in keywords)


def fetch_article(url):
    try:
        response = requests.get(url, timeout=12, headers=HEADERS)
        if not response.ok:
            return "", ""

        image_url = ""
        og_match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            response.text,
        )
        if not og_match:
            og_match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                response.text,
            )
        if og_match:
            image_url = og_match.group(1)

        text = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
        )
        if not text:
            return "", image_url
        return text, image_url
    except Exception as exc:
        print(f"Text fetch error: {exc}")
        return "", ""


def format_post(article):
    title = collapse_spaces(article.get("title", ""))
    body = clean_body(article.get("body", ""), title=title, source=article.get("source", ""))
    flag = detect_flag(title + " " + body)
    if body:
        return f"{flag} {title}\n\n{body}"
    return f"{flag} {title}"


def send_message(text, image_url=""):
    if not ACCESS_TOKEN:
        raise RuntimeError("ACCESS_TOKEN is not set")
    payload = {"text": text}
    if image_url:
        payload["attachments"] = [{"type": "image", "payload": {"url": image_url}}]

    try:
        response = requests.post(
            f"{MAX_API}/messages",
            params={"chat_id": CHAT_ID},
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": ACCESS_TOKEN,
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if not response.ok and image_url:
            payload.pop("attachments", None)
            response = requests.post(
                f"{MAX_API}/messages",
                params={"chat_id": CHAT_ID},
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": ACCESS_TOKEN,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
        if not response.ok:
            print(f"MAX API error: {response.status_code} {response.text}")
        return response.ok
    except Exception as exc:
        print(f"Send error: {exc}")
        return False


def get_article_id(url):
    return hashlib.md5(url.encode()).hexdigest()


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
    cutoff = datetime.now(timezone.utc) - timedelta(hours=QUEUE_MAX_AGE_HOURS)
    queue = [
        item
        for item in load_json_file(QUEUE_FILE, [])
        if (parse_dt(item.get("pub_dt")) or cutoff) >= cutoff
    ]
    queue = dedupe_articles(queue)
    return queue[:MAX_QUEUE_SIZE]


def save_queue(queue):
    queue = dedupe_articles(queue)
    save_json_file(QUEUE_FILE, queue[:MAX_QUEUE_SIZE])


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
                summary = strip_html(entry.get("summary", entry.get("description", "")))
                if not title or not url:
                    continue

                if any(pattern in url for pattern in source.get("exclude_url_patterns", ())):
                    continue

                include_keywords = source.get("include_keywords")
                if include_keywords and not matches_keywords(f"{title} {summary}", include_keywords):
                    continue

                article_id = get_article_id(url)
                title_key = normalize_title(title)
                if article_id in posted or article_id in queued_ids or title_key in queued_titles:
                    continue

                pub = entry.get("published_parsed")
                pub_dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else now
                if pub_dt > now + timedelta(hours=MAX_FUTURE_SKEW_HOURS):
                    continue
                if pub_dt < cutoff:
                    continue

                collected.append(
                    {
                        "id": article_id,
                        "title": title,
                        "url": url,
                        "source": source["name"],
                        "pub_dt": pub_dt.isoformat(),
                        "no_image": source.get("no_image", False),
                        "priority_boost_minutes": source.get("priority_boost_minutes", 0),
                    }
                )
                queued_ids.add(article_id)
                queued_titles.add(title_key)
        except Exception as exc:
            print(f"Error fetching {source['name']}: {exc}")

    queue.extend(collected)
    queue = dedupe_articles(queue)
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
    body, image_url = fetch_article(article["url"])
    if article.get("no_image"):
        image_url = ""
    article["body"] = body

    if not send_message(format_post(article), image_url):
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
