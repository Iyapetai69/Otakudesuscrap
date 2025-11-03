#!/usr/bin/env python3
# scraper_all_optimized_tor.py
# TOR MODE: SOCKS5 proxy + stem control for IP rotation. Anti-403 forever. Run direct in Actions.

import logging
import requests
import cloudscraper
from bs4 import BeautifulSoup
import time
import json
from pathlib import Path
import re
from urllib.parse import urljoin
import sys
import traceback
import random
import threading

# Selenium + Undetected
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# Tor control
from stem import Signal
from stem.control import Controller

# -------- Logging --------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -------- CONFIG --------
BASE_URL = "https://otakudesu.best"
RATE_LIMIT = 5.0  # Tor lambat, delay lebih
RETRIES = 5
TIMEOUT = 90
TOR_PROXY = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}  # SOCKS5 via Tor
TOR_CONTROL_PORT = 9051  # Default control port

OUT = Path("outputs")
OUT_HOME = OUT / "home"
OUT_ONGOING = OUT / "ongoing"
OUT_GENRE = OUT / "genrelist"
OUT_JADWAL = OUT / "jadwal"
OUT_ANIME = OUT / "anime"
OUT_EPISODES = OUT / "episodes"
OUT_EPISODE = OUT / "episode"

for p in [OUT, OUT_HOME, OUT_ONGOING, OUT_GENRE, OUT_JADWAL, OUT_ANIME, OUT_EPISODES, OUT_EPISODE]:
    p.mkdir(parents=True, exist_ok=True)

# -------- Tor Control --------
def rotate_tor_ip():
    """Rotate Tor circuit: New IP via signal NEWNYM."""
    try:
        with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
            controller.authenticate()  # Password kosong default
            controller.signal(Signal.NEWNYM)
            logger.info("Tor IP rotated! New circuit active.")
            time.sleep(10)  # Wait for new circuit
    except Exception as e:
        logger.error(f"Tor rotate fail: {e}. Manual retry later.")

# -------- Headers (10 UA) --------
def generate_headers():
    base = {
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0"
    }
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ]
    headers_list = []
    for ua in uas:
        h = base.copy()
        h["User-Agent"] = ua
        headers_list.append(h)
    return headers_list

HEADERS_LIST = generate_headers()

# -------- Scraper: Cloudscraper + Tor --------
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    delay=10
)

def get_undetected_driver():
    """Undetected Chrome + Tor proxy."""
    options = uc.ChromeOptions()
    options.headless = True
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={random.choice(HEADERS_LIST)['User-Agent']}")
    options.add_argument("--proxy-server=socks5://127.0.0.1:9050")  # Tor SOCKS
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    try:
        driver = uc.Chrome(options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        logger.error(f"Driver fail: {e}")
        return None

# -------- Fetch: Tor Beast --------
def fetch(url, retries=RETRIES, timeout=TIMEOUT):
    backoff = 1
    for attempt in range(1, retries + 1):
        headers = random.choice(HEADERS_LIST)
        try:
            logger.info(f"[TOR CLOUDSCRAPER] {url} (att {attempt}/{retries}) UA={headers['User-Agent'][:40]}...")
            r = scraper.get(url, headers=headers, proxies=TOR_PROXY, timeout=timeout)
            if r.status_code == 403:
                logger.warning("403! Rotate Tor IP + fallback undetected...")
                rotate_tor_ip()
                return fetch_with_undetected(url)
            r.raise_for_status()
            jitter = random.uniform(3, 8)  # Tor jitter
            time.sleep(RATE_LIMIT + jitter)
            return r.text
        except requests.exceptions.HTTPError as he:
            if he.response and he.response.status_code == 403:
                rotate_tor_ip()
                return fetch_with_undetected(url)
            logger.error(f"HTTP error: {he}")
        except Exception as e:
            logger.error(f"Tor error: {e}")
        if attempt < retries:
            sleep = backoff * (5 + random.uniform(2, 6))
            logger.info(f"Tor backoff {sleep}s...")
            time.sleep(sleep)
            backoff *= 2
            rotate_tor_ip()  # Rotate tiap fail
    logger.error(f"Tor dead on {url}. Try manual trigger.")
    return None

def fetch_with_undetected(url):
    driver = get_undetected_driver()
    if not driver:
        return None
    try:
        logger.info(f"[TOR UNDETECTED] {url}...")
        driver.get(url)
        WebDriverWait(driver, 40).until(
            EC.any_of(
                EC.title_contains("Otakudesu"),
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        )
        driver.execute_script("window.scrollTo(0, Math.random() * document.body.scrollHeight);")
        time.sleep(random.uniform(10, 20))  # Tor + CF wait
        if "cloudflare" in driver.page_source.lower():
            rotate_tor_ip()
            driver.refresh()
            time.sleep(15)
        html = driver.page_source
        logger.info(f"[TOR SUCCESS] {len(html)} chars.")
        return html
    except Exception as e:
        logger.error(f"Undetected fail: {e}")
    finally:
        driver.quit()
    return None

# -------- Soup & Save --------
def soup_from_url(url):
    html = fetch(url)
    if not html:
        return None
    return BeautifulSoup(html, "html.parser")

def save_json(data, filename, folder):
    path = Path(folder) / filename
    if path.exists():
        logger.info(f"[skip] {path}")
        return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"[saved] {path}")
    return True

def slug_from_url(url):
    if not url:
        return None
    return url.rstrip("/").split("/")[-1]

# -------- Scrapers --------
def scrape_home():
    filename = "home.json"
    if (OUT_HOME / filename).exists():
        logger.info(f"Skipping home: {filename} exists")
        try:
            return json.loads((OUT_HOME / filename).read_text(encoding="utf-8"))
        except:
            logger.warning("Corrupt home.json, rescraping")
    soup = soup_from_url(BASE_URL)
    if not soup:
        return []
    results = []
    for li in soup.select("div.venz ul li"):
        title = li.select_one("h2.jdlflm")
        a = li.select_one("a")
        img = li.select_one("div.thumbz img")
        ep = li.select_one("div.epz")
        ep_tipe = li.select_one("div.epztipe")
        date = li.select_one("div.newnime")
        item = {
            "title": title.get_text(strip=True) if title else None,
            "link": a.get("href") if a and a.has_attr("href") else None,
            "slug": slug_from_url(a.get("href")) if a and a.has_attr("href") else None,
            "thumbnail": img.get("src") if img and img.has_attr("src") else None,
            "latest_episode": ep.get_text(strip=True) if ep else None,
            "day": ep_tipe.get_text(strip=True) if ep_tipe else None,
            "date": date.get_text(strip=True) if date else None
        }
        results.append(item)
    save_json(results, filename, OUT_HOME)
    return results

def scrape_ongoing_pages(max_pages=200):
    all_items = []
    for page in range(1, max_pages + 1):
        filename = f"ongoing_p{page}.json"
        if (OUT_ONGOING / filename).exists():
            logger.info(f"Skipping ongoing p{page}: {filename}")
            try:
                items = json.loads((OUT_ONGOING / filename).read_text(encoding="utf-8"))
                all_items.extend(items)
                continue
            except:
                logger.warning(f"Corrupt {filename}, rescraping")
        url = f"{BASE_URL}/ongoing-anime/" if page == 1 else f"{BASE_URL}/ongoing-anime/page/{page}/"
        soup = soup_from_url(url)
        if not soup:
            break
        items = []
        for li in soup.select("div.venz ul li"):
            a = li.select_one("a")
            img = li.select_one("div.thumbz img")
            title = li.select_one("h2.jdlflm")
            ep = li.select_one("div.epz")
            item = {
                "title": title.get_text(strip=True) if title else None,
                "link": a.get("href") if a and a.has_attr("href") else None,
                "slug": slug_from_url(a.get("href")) if a and a.has_attr("href") else None,
                "thumbnail": img.get("src") if img and img.has_attr("src") else None,
                "latest_episode": ep.get_text(strip=True) if ep else None
            }
            items.append(item)
        if not items:
            break
        save_json(items, filename, OUT_ONGOING)
        all_items.extend(items)
        if page % 20 == 0:
            rotate_tor_ip()
    seen = set()
    unique = [it for it in all_items if it.get("slug") and it["slug"] not in seen and not seen.add(it["slug"])]
    save_json(unique, "ongoing_all_unique.json", OUT_ONGOING)
    return unique

def scrape_genrelist():
    filename = "genrelist.json"
    if (OUT_GENRE / filename).exists():
        logger.info(f"Skipping genre list: {filename} exists")
        try:
            return json.loads((OUT_GENRE / filename).read_text(encoding="utf-8"))
        except Exception:
            logger.warning(f"Corrupt file {filename}, rescraping...")
    url = f"{BASE_URL}/genre-list/"
    soup = soup_from_url(url)
    if not soup:
        return []
    results = []
    for a in soup.select("#venkonten .vezone ul.genres li a, div.genres li a, .genres li a"):
        results.append({
            "name": a.get_text(strip=True),
            "link": a.get("href")
        })
    save_json(results, filename, OUT_GENRE)
    return results

def scrape_jadwal():
    filename = "jadwalrilis.json"
    if (OUT_JADWAL / filename).exists():
        logger.info(f"Skipping jadwal: {filename} exists")
        try:
            return json.loads((OUT_JADWAL / filename).read_text(encoding="utf-8"))
        except Exception:
            logger.warning(f"Corrupt file {filename}, rescraping...")
    url = f"{BASE_URL}/jadwal-rilis/"
    soup = soup_from_url(url)
    if not soup:
        return {}
    jadwal = {}
    for box in soup.select("div.jadwal-konten"):
        day_el = box.select_one("h2")
        day = day_el.get_text(strip=True) if day_el else "unknown"
        items = []
        for li in box.select("ul li"):
            a = li.select_one("a")
            if a and a.has_attr("href"):
                items.append({"title": a.get_text(strip=True), "link": a.get("href")})
        jadwal[day] = items
    save_json(jadwal, filename, OUT_JADWAL)
    return jadwal

def scrape_anime_detail_by_slug(slug):
    filename = f"{slug}.json"
    if (OUT_ANIME / filename).exists():
        logger.info(f"Skipping anime {slug}: {filename} exists")
        try:
            return json.loads((OUT_ANIME / filename).read_text(encoding="utf-8"))
        except Exception:
            logger.warning(f"Corrupt file {filename}, rescraping...")
    url = f"{BASE_URL}/anime/{slug}/"
    soup = soup_from_url(url)
    if not soup:
        return None
    title = None
    t = soup.select_one(".infozin .infozingle p:first-child span, .jdlrx h1, h1, .post-title")
    if t:
        title = t.get_text(strip=True).replace("Judul: ", "")
    synopsis = None
    syn = soup.select_one(".sinopsis, .sinopc, .sinopc p, #venkonten .sinopsis, .entry-content .sinopsis")
    if syn:
        synopsis = syn.get_text("\n", strip=True)
    poster = None
    pimg = soup.select_one(".detpost .thumb .thumbz img, .fotoanime img, .post img, meta[property='og:image']")
    if pimg:
        if pimg.name == "meta":
            poster = pimg.get("content")
        else:
            poster = pimg.get("src") or pimg.get("data-src")
    genres = [g.get_text(strip=True) for g in soup.select("#venkonten .vezone ul.genres li a, .infozingle a[href*='genres'], .genre-info a, .genres a")]
    info = {}
    for p in soup.select(".infozin .infozingle p"):
        txt = p.get_text(" ", strip=True)
        if "Skor" in txt or "Skor:" in txt:
            info["score"] = txt.replace("Skor:", "").replace("Skor", "").strip()
        if "Produser" in txt or "Produser:" in txt:
            info["producer"] = txt.split("Produser")[-1].replace(":", "").strip()
        if "Tipe" in txt or "Type" in txt:
            info["type"] = txt.split("Tipe")[-1].replace(":", "").strip()
        if "Status" in txt:
            info["status"] = txt.split("Status")[-1].replace(":", "").strip()
    episodes = []
    episodelists = soup.select(".episodelist")
    chosen = None
    if len(episodelists) >= 2:
        chosen = episodelists[1]
    elif len(episodelists) >= 1:
        chosen = episodelists[0]
    if chosen:
        for li in chosen.select("ul li, li"):
            a = li.select_one("a")
            if not a or not a.has_attr("href"):
                continue
            ep_url = a.get("href")
            ep_slug = slug_from_url(ep_url)
            episodes.append({
                "title": a.get_text(strip=True),
                "link": ep_url,
                "slug": ep_slug
            })
    if not episodes:
        for a in soup.select("a[href*='/episode/'], a[href*='episode']"):
            href = a.get("href")
            episodes.append({"title": a.get_text(strip=True), "link": href, "slug": slug_from_url(href)})
    data = {
        "title": title,
        "slug": slug,
        "url": url,
        "poster": poster,
        "synopsis": synopsis,
        "genres": genres,
        "info": info,
        "episodes": episodes
    }
    save_json(data, filename, OUT_ANIME)
    if len(episodes) > 50:  # Rotate kalau banyak episode
        rotate_tor_ip()
    return data

def scrape_episode_detail_by_slug(slug):
    filename = f"{slug}.json"
    if (OUT_EPISODE / filename).exists():
        logger.info(f"Skipping episode {slug}: {filename} exists")
        try:
            return json.loads((OUT_EPISODE / filename).read_text(encoding="utf-8"))
        except Exception:
            logger.warning(f"Corrupt file {filename}, rescraping...")
    url = f"{BASE_URL}/episode/{slug}/"
    soup = soup_from_url(url)
    if not soup:
        return None
    title_el = soup.select_one(".venutama .posttl, h1, .post-title")
    title = title_el.get_text(strip=True) if title_el else None
    iframe = soup.select_one("#pembed iframe, iframe[src], .player iframe")
    embed_url = iframe.get("src") if iframe and iframe.has_attr("src") else None
    embeds = [i.get("src") for i in soup.select("iframe[src]") if i and i.has_attr("src")]
    downloads = []
    for container in soup.select(".download, .dlbutton, .downloadlinks"):
        for a in container.select("a[href]"):
            downloads.append({"host": a.get_text(strip=True), "link": a.get("href")})
    for li in soup.select(".download ul li, .dowload-servers li"):
        qa = li.select_one("strong")
        quality = qa.get_text(strip=True) if qa else None
        links = []
        for a in li.select("a[href]"):
            links.append({"host": a.get_text(strip=True), "link": a.get("href")})
        if links:
            downloads.append({"quality": quality, "links": links})
    flir_anchors = [a.get("href") for a in soup.select(".flir a[href]") if a and a.has_attr("href")]
    anime_url = None
    if flir_anchors:
        anime_url = flir_anchors[0]
    data = {
        "title": title,
        "slug": slug,
        "url": url,
        "embed_url": embed_url,
        "embeds": embeds,
        "downloads": downloads,
        "anime_url": anime_url
    }
    save_json(data, filename, OUT_EPISODE)
    return data

# -------- Run All --------
def run_all():
    logger.info("TOR MODE ON. Starting Otakudesu scrape...")
    scrape_home()
    ongoing = scrape_ongoing_pages()
    scrape_genrelist()
    scrape_jadwal()
    slugs = set(it["slug"] for it in ongoing if it.get("slug"))
    # Load home slugs
    if (OUT_HOME / "home.json").exists():
        try:
            home = json.loads((OUT_HOME / "home.json").read_text())
            slugs.update(it["slug"] for it in home if it.get("slug"))
        except:
            pass
    logger.info(f"{len(slugs)} slugs. Detail scrape...")
    ep_queue = set()
    for i, slug in enumerate(sorted(slugs), 1):
        logger.info(f"[{i}/{len(slugs)}] Anime: {slug}")
        ad = scrape_anime_detail_by_slug(slug)
        if ad:
            for ep in ad.get("episodes", []):
                ep_slug = slug_from_url(ep.get("link"))
                if ep_slug:
                    ep_queue.add(ep_slug)
        if i % 10 == 0:
            rotate_tor_ip()
    logger.info(f"{len(ep_queue)} episodes. Go!")
    for j, ep_slug in enumerate(sorted(ep_queue), 1):
        logger.info(f"[{j}/{len(ep_queue)}] Episode: {ep_slug}")
        scrape_episode_detail_by_slug(ep_slug)
        if j % 5 == 0:
            rotate_tor_ip()
    logger.info("TOR SCRAPE DONE. No 403 allowed!")

if __name__ == "__main__":
    run_all()
