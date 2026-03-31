import feedparser
import requests
import trafilatura
import os
import hashlib
import json
import time
import re
import socket
from datetime import datetime, timezone, timedelta

socket.setdefaulttimeout(15)

BOT_TOKEN = os.environ['BOT_TOKEN']
CHANNEL = os.environ.get('CHANNEL', '@bozhespartakhranii')  # заменить на MAX-канал

SOURCES = [
    {'name': 'ТАСС',  'url': 'https://tass.ru/rss/v2.xml'},
    {'name': 'РИА',   'url': 'https://ria.ru/export/rss2/archive/index.xml'},
    {'name': 'Лента', 'url': 'https://lenta.ru/rss/news'},
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

TEXT_LIMIT = 3500

# Флаги стран по ключевым словам в заголовке/тексте
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
    ('🌍', []),  # fallback — мировые новости
]


def detect_flag(text):
    text_lower = text.lower()
    for flag, keywords in FLAGS:
        if not keywords:
            continue
        if any(kw in text_lower for kw in keywords):
            return flag
    return '🌍'


def fetch_article_text(url):
    try:
        r = requests.get(url, timeout=12, headers=HEADERS)
        if not r.ok:
            return ''
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
        if not text:
            return ''
        chunk = text[:TEXT_LIMIT]
        if len(text) > TEXT_LIMIT:
            dot = chunk.rfind('.')
            chunk = chunk[:dot + 1] if dot > TEXT_LIMIT // 2 else chunk.rstrip() + '...'
        return chunk
    except Exception as e:
        print(f'Text fetch error: {e}')
        return ''


def escape_html(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def format_post(title, body, source_name, pub_dt):
    msk = timezone(timedelta(hours=3))
    time_str = pub_dt.astimezone(msk).strftime('%H:%M') if pub_dt else ''
    flag = detect_flag(title + ' ' + body)
    text = f'{flag} <b>{escape_html(title)}</b>'
    if body:
        text += f'\n\n{escape_html(body)}'
    text += f'\n\n📰 {source_name}'
    if time_str:
        text += f' | 🕐 {time_str} МСК'
    return text


def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    resp = requests.post(url, json={
        'chat_id': CHANNEL,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if not resp.ok:
        print(f'Telegram error: {resp.text}')
    return resp.ok


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
                })

        except Exception as e:
            print(f'Error fetching {source["name"]}: {e}')

    # Дедупликация по заголовку
    seen = set()
    unique = []
    for a in new_articles:
        key = re.sub(r'\W+', '', a['title'].lower())[:50]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    unique.sort(key=lambda x: x['pub_dt'])
    to_post = unique[:4]

    if not to_post:
        print('No new articles found.')
        save_posted(posted)
        return

    WINDOW = 28 * 60
    interval = WINDOW / (len(to_post) - 1) if len(to_post) > 1 else 0

    posted_count = 0
    for i, article in enumerate(to_post):
        if i > 0:
            time.sleep(interval)

        body = fetch_article_text(article['url'])
        text = format_post(article['title'], body, article['source'], article['pub_dt'])
        if send_telegram(text):
            posted.add(article['id'])
            posted_count += 1
            print(f'Posted: {article["title"]}')

    print(f'Done. Posted {posted_count} articles.')
    save_posted(posted)


if __name__ == '__main__':
    main()
