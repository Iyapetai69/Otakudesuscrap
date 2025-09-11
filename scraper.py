import sys
import os
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

# Configuration
BASE_URL = "https://otakudesu.best"  # Hardcoded ke domain aktif terbaru
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
RATE_LIMIT_SECONDS = 1.5  # Delay between requests to reduce rate limit
OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Simple helper utils
def _get_soup(url: str) -> BeautifulSoup:
    print(f"GET: {url}")
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    time.sleep(RATE_LIMIT_SECONDS)
    return BeautifulSoup(res.text, "html.parser")

def _write_json(name: str, data: Any):
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(OUTPUT_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"scraped_at": ts, "data": data}, f, ensure_ascii=False, indent=2)
    print(f"Saved -> {path}")

# --- Selectors / parsing rules ---
# These are conservative, best-effort selectors. If some fields are missing, code falls back gracefully.
selectors = {
    "home_item": {
        "container": ".wrapper .anime_list, .listupd, .post-listing, .thumb",
        "title": "a[href]",
        "link": "a[href]",
        "thumbnail": "img[src]",
        "meta": ".episode, .ep, .meta"
    },
    "anime_detail": {
        "title": ".post-title, h1, .detail .title",
        "synopsis": ".sinopsis, .entry-content, .summary, .anime__sinopsis",
        "info_rows": ".info-stats, .detail .spec, .dlopis, .anime-info"
    },
    "episodes_list": {
        "container": ".episode_list, .eps, .list-episode, .episodelist",
        "episode_item": "a[href]"
    },
    "episode_detail": {
        "title": "h1, .episode-title",
        "embed": "iframe[src], .player iframe, .embed-responsive iframe",
        "download_links": ".download, .dlbutton a, .downloads a"
    },
    "genre_list": {
        "container": ".post-listing, .anime_list, .wrapper",
        "item": "a[href]"
    }
}

# --- Scrapers ---

def scrape_home(page: int = 1) -> List[Dict[str, Any]]:
    """Scrape the home page (or page X) for list of recent anime/posts."""
    url = f"{BASE_URL}/" if page == 1 else f"{BASE_URL}/page/{page}/"
    soup = _get_soup(url)

    items = []
    # Attempt a few different container queries
    candidates = soup.select('.listupd .venser, .post, .anime_list .anime, .thumb, .listupd li, .post-listing article')
    if not candidates:
        # fallback: find anchors inside main content
        candidates = soup.select('main a[href]')

    for c in candidates:
        try:
            link_tag = c.select_one('a[href]')
            title = link_tag.get_text(strip=True) if link_tag else (c.get('title') or c.get_text(strip=True))
            href = link_tag['href'] if link_tag and link_tag.has_attr('href') else None
            thumb = None
            img = c.select_one('img')
            if img and img.has_attr('src'):
                thumb = img['src']
            items.append({'title': title, 'url': href, 'thumbnail': thumb})
        except Exception as e:
            # skip malformed
            continue

    _write_json('home', items)
    return items

def scrape_anime_detail(slug_or_url: str) -> Dict[str, Any]:
    """Scrape anime detail page. Accept slug (relative) or full url."""
    if slug_or_url.startswith('http'):
        url = slug_or_url
    else:
        url = f"{BASE_URL}/anime/{slug_or_url}" if '/anime/' not in slug_or_url else f"{BASE_URL}/{slug_or_url.lstrip('/')}"

    soup = _get_soup(url)

    # title
    title_tag = soup.select_one('h1, .post-title, .title')
    title = title_tag.get_text(strip=True) if title_tag else None

    # synopsis
    synopsis_tag = soup.select_one('.sinopsis, .entry-content, .summary, .anime__sinopsis')
    synopsis = synopsis_tag.get_text(strip=True) if synopsis_tag else None

    # other info like genre, status, type, producer
    info = {}
    # attempt to find rows of info in dl or ul
    possible_info = soup.select('.post-content .info, .detail .spec, .anime_info, .dlopis, .post .meta')
    for p in possible_info:
        text = p.get_text(separator='|', strip=True)
        # naive split key:value pairs
        if ':' in text or '\n' in text or '|' in text:
            parts = [x.strip() for x in text.split('|') if x.strip()]
            for part in parts:
                if ':' in part:
                    k, v = part.split(':', 1)
                    info[k.strip().lower()] = v.strip()

    # genres - try to grab genre links
    genres = [a.get_text(strip=True) for a in soup.select('a[href*="genre"], .genres a, .genre a')]

    data = {
        'title': title,
        'url': url,
        'synopsis': synopsis,
        'info': info,
        'genres': genres
    }

    _write_json(f'anime_detail_{slug_or_url.replace("/","_")}', data)
    return data

def scrape_episodes_list(slug_or_url: str) -> List[Dict[str, Any]]:
    if slug_or_url.startswith('http'):
        url = slug_or_url
    else:
        url = f"{BASE_URL}/anime/{slug_or_url}" if '/anime/' not in slug_or_url else f"{BASE_URL}/{slug_or_url.lstrip('/')}"

    soup = _get_soup(url)
    eps = []
    # common pattern: list of episode links
    containers = soup.select('.eps, .episode_list, .list-episode, .episodelist, .venser ul li')
    if not containers:
        containers = soup.select('a[href*="episode"], a[href*="/ep-"]')

    # collect anchors
    anchors = []
    for c in containers:
        anchors.extend(c.select('a[href]'))
    # dedupe by href
    seen = set()
    for a in anchors:
        href = a['href']
        if href in seen: continue
        seen.add(href)
        title = a.get_text(strip=True)
        eps.append({'title': title, 'url': href})

    _write_json(f'episodes_{slug_or_url.replace("/","_")}', eps)
    return eps

def scrape_episode_detail(slug_or_url: str) -> Dict[str, Any]:
    if slug_or_url.startswith('http'):
        url = slug_or_url
    else:
        url = f"{BASE_URL}/episode/{slug_or_url}" if '/episode/' not in slug_or_url else f"{BASE_URL}/{slug_or_url.lstrip('/')}"

    soup = _get_soup(url)

    title = soup.select_one('h1, .episode-title')
    title = title.get_text(strip=True) if title else None

    # find iframe embed
    iframe = soup.select_one('iframe[src], .player iframe')
    embed_url = iframe['src'] if iframe and iframe.has_attr('src') else None

    # find download links
    dl_links = [a['href'] for a in soup.select('.download a, .dlbutton a, a[href*="download"], a[href*="drive.google"]') if a.has_attr('href')]

    data = {
        'title': title,
        'url': url,
        'embed_url': embed_url,
        'download_links': dl_links
    }

    _write_json(f'episode_{slug_or_url.replace("/","_")}', data)
    return data

def scrape_genre_list(slug_or_url: str, page: int = 1) -> List[Dict[str, Any]]:
    if slug_or_url.startswith('http'):
        url = slug_or_url
    else:
        url = f"{BASE_URL}/genre/{slug_or_url}" if '/genre/' not in slug_or_url else f"{BASE_URL}/{slug_or_url.lstrip('/')} "
    if page > 1:
        url = url.rstrip('/') + f"/page/{page}/"

    soup = _get_soup(url)
    items = []
    anchors = soup.select('.post-listing a[href], .anime_list a[href], .listupd a[href]')
    for a in anchors:
        href = a['href']
        title = a.get_text(strip=True)
        items.append({'title': title, 'url': href})

    _write_json(f'genre_{slug_or_url.replace("/","_")}_p{page}', items)
    return items

def scrape_complete_anime(page: int = 1) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/complete-anime/" if page == 1 else f"{BASE_URL}/complete-anime/page/{page}/"
    soup = _get_soup(url)
    items = []
    anchors = soup.select('.post-listing a[href], .anime_list a[href], .listupd a[href]')
    for a in anchors:
        items.append({'title': a.get_text(strip=True), 'url': a['href']})
    _write_json(f'complete_anime_p{page}', items)
    return items

def scrape_ongoing_anime() -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/ongoing-anime/"
    soup = _get_soup(url)
    items = []
    anchors = soup.select('.post-listing a[href], .anime_list a[href], .listupd a[href]')
    for a in anchors:
        items.append({'title': a.get_text(strip=True), 'url': a['href']})
    _write_json('ongoing_anime', items)
    return items

# --- CLI ---

def usage():
    print("Usage: python scraper.py <all|home|anime|episodes|episode|genre|complete|ongoing> [arg]")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'all':
        scrape_home()
        scrape_complete_anime()
        scrape_ongoing_anime()
    elif cmd == 'home':
        page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        scrape_home(page)
    elif cmd == 'anime':
        if len(sys.argv) < 3:
            print('Provide slug or url')
            sys.exit(1)
        scrape_anime_detail(sys.argv[2])
    elif cmd == 'episodes':
        if len(sys.argv) < 3:
            print('Provide anime slug or url')
            sys.exit(1)
        scrape_episodes_list(sys.argv[2])
    elif cmd == 'episode':
        if len(sys.argv) < 3:
            print('Provide episode slug or url')
            sys.exit(1)
        scrape_episode_detail(sys.argv[2])
    elif cmd == 'genre':
        if len(sys.argv) < 3:
            print('Provide genre slug')
            sys.exit(1)
        page = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        scrape_genre_list(sys.argv[2], page)
    elif cmd == 'complete':
        page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        scrape_complete_anime(page)
    elif cmd == 'ongoing':
        scrape_ongoing_anime()
    else:
        usage()
