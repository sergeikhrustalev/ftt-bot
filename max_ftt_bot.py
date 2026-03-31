import feedparser
import requests
import trafilatura
import os
import hashlib
import json
import re
import socket
from datetime import datetime, timezone, timedelta

socket.setdefaulttimeout(15)

ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
CHAT_ID = -72873687632407  # канал "Боже, Спартак храни!" перепрофилирован под мировые новости

MAX_API = 'https://botapi.max.ru'

SOURCES = [
    {'name': 'ТАСС',        'url': 'https://tass.ru/rss/v2.xml',                  'no_image': False},
    {'name': 'РИА',         'url': 'https://ria.ru/export/rss2/archive/index.xml', 'no_image': False},
    {'name': 'Коммерсантъ', 'url': 'https://www.kommersant.ru/RSS/main.xml',       'no_image': False},
    {'name': 'RT',          'url': 'https://russian.rt.com/rss',                   'no_image': False},
    {'name': 'Ведомости',   'url': 'https://www.vedomosti.ru/rss/news',            'no_image': False},
    {'name': 'Лента',       'url': 'https://lenta.ru/rss/news',                    'no_image': True},
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

TEXT_LIMIT = 500

FLAGS = [
    ('🇷🇺', ['россия', 'российск', 'москва', 'кремль', 'путин', 'медведев']),
    ('🇺🇸', ['сша', 'американ', 'вашингтон', 'байден', 'трамп', 'белый дом']),
    ('🇨🇳', ['китай', 'китайск', 'пекин', 'си цзиньпин']),
    ('🇺🇦', ['украина', 'украинск', 'киев', 'зеленский']),
    ('🇩🇪', ['германия', 'немецк', 'берлин']),
    ('🇬🇧', ['великобритания', 'британ', 'лондон']),
    ('🇫🇷', ['франция', 'французск', 'париж', 'макрон']),
    ('🇮🇱', ['израиль', 'израильск', 'тель-авив']),
    ('🇮🇷', ['иран', 'иранск', 'тегеран']),
    ('🇹🇷', ['турция', 'турецк', 'анкара', 'эрдоган']),
    ('🇯🇵', ['япония', 'японск', 'токио']),
    ('🇰🇷', ['южная корея', 'корейск', 'сеул']),
    ('🇰🇵', ['северная корея', 'пхеньян', 'ким чен']),
    ('🇸🇾', ['сирия', 'сирийск', 'дамаск']),
    ('🇵🇸', ['палестина', 'палестинск', 'газа', 'хамас']),
    ('🇸🇦', ['саудовск', 'эр-рияд']),
    ('🇮🇳', ['индия', 'индийск', 'нью-дели', 'моди']),
    ('🇧🇷', ['бразилия', 'бразильск']),
    ('🇦🇺', ['австралия', 'австралийск']),
    ('🇨🇦', ['канада', 'канадск', 'оттава']),
    ('🌍', []),
]


def detect_flag(text):
    text_lower = text.lower()
    for flag, keywords in FLAGS:
        if not keywords:
            continue
        if any(kw in text_lower for kw in keywords):
            return flag
    return '🌍'


def fetch_article(url):
    """Возвращает (text, image_url)."""
    try:
        r = requests.get(url, timeout=12, headers=HEADERS)
        if not r.ok:
            return '', ''
        # og:image
        image_url = ''
        og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', r.text)
        if not og_match:
            og_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r.text)
        if og_match:
            image_url = og_match.group(1)

        text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
        if not text:
            return '', image_url
        if len(text) > TEXT_LIMIT:
            chunk = text[:TEXT_LIMIT]
            dot = chunk.rfind('.')
            chunk = chunk[:dot + 1] if dot > TEXT_LIMIT // 2 else chunk.rstrip() + '...'
            return chunk, image_url
        return text, image_url
    except Exception as e:
        print(f'Text fetch error: {e}')
        return '', ''


def format_post(title, body, source_name, pub_dt):
    flag = detect_flag(title + ' ' + body)
    text = f'{flag} {body}' if body else f'{flag} {title}'
    return text


def send_message(text, image_url=''):
    import json as _json
    try:
        payload = {'text': text}
        if image_url:
            payload['attachments'] = [{'type': 'image', 'payload': {'url': image_url}}]
        resp = requests.post(
            f'{MAX_API}/messages',
            params={'chat_id': CHAT_ID},
            data=_json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': ACCESS_TOKEN,
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        if not resp.ok:
            print(f'MAX API error: {resp.status_code} {resp.text}')
            # Попытка без фото если с фото упало
            if image_url:
                payload.pop('attachments')
                resp = requests.post(
                    f'{MAX_API}/messages',
                    params={'chat_id': CHAT_ID},
                    data=_json.dumps(payload).encode('utf-8'),
                    headers={'Authorization': ACCESS_TOKEN, 'Content-Type': 'application/json'},
                    timeout=15,
                )
        if resp.ok:
            print(f'MAX API ok')
        return resp.ok
    except Exception as e:
        print(f'Send error: {e}')
        return False


def get_article_id(url):
    return hashlib.md5(url.encode()).hexdigest()


def load_posted():
    if os.path.exists('posted.json'):
        with open('posted.json') as f:
            return set(json.load(f))
    return set()


def save_posted(posted):
    with open('posted.json', 'w') as f:
        json.dump(list(posted), f)


def main():
    posted = load_posted()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=4)

    new_articles = []

    for source in SOURCES:
        try:
            feed = feedparser.parse(source['url'], request_headers=HEADERS)
            if feed.bozo and not feed.entries:
                print(f'Feed error {source["name"]}: {feed.bozo_exception}')
                continue

            for entry in feed.entries:
                title = entry.get('title', '').strip()
                url = entry.get('link', '').strip()
                if not title or not url:
                    continue

                article_id = get_article_id(url)
                if article_id in posted:
                    continue

                pub = entry.get('published_parsed')
                pub_dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else now
                if pub_dt < cutoff:
                    continue

                new_articles.append({
                    'id': article_id,
                    'title': title,
                    'url': url,
                    'source': source['name'],
                    'pub_dt': pub_dt,
                    'no_image': source.get('no_image', False),
                })

        except Exception as e:
            print(f'Error fetching {source["name"]}: {e}')

    seen = set()
    unique = []
    for a in new_articles:
        key = re.sub(r'\W+', '', a['title'].lower())[:50]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    unique.sort(key=lambda x: x['pub_dt'])
    to_post = unique[:1]

    if not to_post:
        print('No new articles found.')
        save_posted(posted)
        return

    posted_count = 0
    for article in to_post:
        body, image_url = fetch_article(article['url'])
        if article.get('no_image'):
            image_url = ''
        text = format_post(article['title'], body, article['source'], article['pub_dt'])
        if send_message(text, image_url):
            posted.add(article['id'])
            posted_count += 1
            print(f'Posted: {article["title"]}')

    print(f'Done. Posted {posted_count} articles.')
    save_posted(posted)


if __name__ == '__main__':
    main()
