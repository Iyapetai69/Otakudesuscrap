#!/usr/bin/env python3
# scraper_all_fixed.py
# Runs full scrape: home, ongoing (paged), genre list, jadwal, all anime details, all episodes details.
# Improved to handle Cloudflare 403 errors
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
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc

# -------- CONFIG --------
BASE_URL = "https://otakudesu.best"
RATE_LIMIT = 3.0         # Increased delay
RETRIES = 5              # More retries
TIMEOUT = 30             # Longer timeout
OUT = Path("outputs")
OUT_HOME = OUT / "home"
OUT_ONGOING = OUT / "ongoing"
OUT_GENRE = OUT / "genrelist"
OUT_JADWAL = OUT / "jadwal"
OUT_ANIME = OUT / "anime"
OUT_EPISODES = OUT / "episodes"
OUT_EPISODE = OUT / "episode"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

for p in [OUT, OUT_HOME, OUT_ONGOING, OUT_GENRE, OUT_JADWAL, OUT_ANIME, OUT_EPISODES, OUT_EPISODE]:
    p.mkdir(parents=True, exist_ok=True)

# -------- Headers loader --------
def load_headers(file="headers.txt"):
    default_headers = [
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0"
        },
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
    ]
    
    try:
        with open(file, "r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        headers_list = [json.loads(line) for line in lines if line.strip()]
        if headers_list:
            return headers_list
    except FileNotFoundError:
        logger.warning(f"Headers file {file} not found, using default headers")
    except Exception as e:
        logger.warning(f"Error loading headers from {file}: {e}, using default headers")
    
    return default_headers

HEADERS_LIST = load_headers("headers.txt")

# -------- Browser Session Management --------
class ScrapingSession:
    def __init__(self):
        self.session = None
        self.driver = None
        self.use_selenium = False
        self._init_session()
    
    def _init_session(self):
        """Initialize cloudscraper session with better settings"""
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            },
            debug=False
        )
        
        # Add default headers to session
        default_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0"
        }
        self.session.headers.update(default_headers)
    
    def _init_selenium(self):
        """Initialize Selenium WebDriver"""
        try:
            options = uc.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = uc.Chrome(options=options)
            self.use_selenium = True
            logger.info("Selenium WebDriver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Selenium: {e}")
            self.use_selenium = False
    
    def get(self, url, headers=None, timeout=30):
        """Get page content with fallback mechanisms"""
        # Try cloudscraper first
        for attempt in range(RETRIES):
            try:
                # Randomize headers
                if HEADERS_LIST:
                    selected_headers = random.choice(HEADERS_LIST)
                    if headers:
                        selected_headers.update(headers)
                    headers = selected_headers
                
                logger.info(f"[GET] {url} (attempt {attempt + 1})")
                
                response = self.session.get(url, headers=headers, timeout=timeout)
                
                # Check for Cloudflare challenge
                if self._is_cloudflare_challenge(response):
                    logger.warning("Cloudflare challenge detected")
                    if not self.use_selenium:
                        self._init_selenium()
                    if self.use_selenium:
                        return self._get_with_selenium(url)
                    else:
                        raise Exception("Cloudflare challenge detected, but Selenium not available")
                
                # Check if response is valid
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 403:
                    logger.warning(f"403 Forbidden on attempt {attempt + 1}")
                    if attempt == RETRIES - 1:
                        # Last attempt - try selenium
                        if not self.use_selenium:
                            self._init_selenium()
                        if self.use_selenium:
                            return self._get_with_selenium(url)
                        else:
                            raise Exception(f"403 Forbidden after {RETRIES} attempts")
                else:
                    logger.warning(f"HTTP {response.status_code} on attempt {attempt + 1}")
                    
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == RETRIES - 1:
                    # Last attempt - try selenium
                    if not self.use_selenium:
                        self._init_selenium()
                    if self.use_selenium:
                        return self._get_with_selenium(url)
                    else:
                        raise e
            
            # Random delay between attempts
            time.sleep(random.uniform(2, 5))
        
        raise Exception("All attempts failed")
    
    def _is_cloudflare_challenge(self, response):
        """Check if response contains Cloudflare challenge"""
        if response.status_code in [403, 503]:
            text = response.text.lower()
            return any(indicator in text for indicator in [
                'checking your browser',
                'cloudflare',
                'checking your browser before accessing',
                'enable javascript',
                'access denied'
            ])
        return False
    
    def _get_with_selenium(self, url):
        """Get page content using Selenium"""
        if not self.driver:
            self._init_selenium()
        
        if self.driver:
            try:
                logger.info(f"Fetching with Selenium: {url}")
                self.driver.get(url)
                time.sleep(random.uniform(3, 7))  # Wait for page to load
                return self.driver.page_source
            except Exception as e:
                logger.error(f"Selenium failed: {e}")
                raise e
        else:
            raise Exception("Selenium not available")
    
    def close(self):
        """Close all resources"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

# Initialize global scraping session
scraper_session = ScrapingSession()

# -------- Helpers --------
def fetch(url, retries=RETRIES, timeout=TIMEOUT):
    """Fetch URL with improved error handling"""
    try:
        html = scraper_session.get(url, timeout=timeout)
        # Random delay to avoid rate limiting
        time.sleep(random.uniform(RATE_LIMIT, RATE_LIMIT + 3))
        return html
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

def soup_from_url(url):
    """Get BeautifulSoup object from URL"""
    html = fetch(url)
    if not html:
        return None
    return BeautifulSoup(html, "html.parser")

def save_json(data, filename, folder):
    """Save data to JSON file"""
    path = Path(folder) / filename
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[saved] {path}")
    except Exception as e:
        logger.error(f"Failed to save {path}: {e}")

def slug_from_url(url):
    """Extract slug from URL"""
    if not url:
        return None
    return url.rstrip("/").split("/")[-1]

# -------- Scrapers --------
# -- Home (root page shows ongoing block) --
def scrape_home():
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
    save_json(results, "home.json", OUT_HOME)
    return results

# -- Ongoing (paged) --
def scrape_ongoing_pages(max_pages=50):  # Reduced max pages for testing
    page = 1
    all_items = []
    while True:
        url = f"{BASE_URL}/ongoing-anime/" if page == 1 else f"{BASE_URL}/ongoing-anime/page/{page}/"
        soup = soup_from_url(url)
        if not soup:
            break
        items = []
        # main container: div.venz ul li (like home)
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
        save_json(items, f"ongoing_p{page}.json", OUT_ONGOING)
        all_items.extend(items)
        page += 1
        if page > max_pages:
            break
    # dedupe by slug
    seen = set()
    unique = []
    for it in all_items:
        if not it.get("slug"): continue
        if it["slug"] in seen: continue
        seen.add(it["slug"])
        unique.append(it)
    save_json(unique, "ongoing_all_unique.json", OUT_ONGOING)
    return unique

# -- Genre list --
def scrape_genrelist():
    url = f"{BASE_URL}/genre-list/"
    soup = soup_from_url(url)
    if not soup:
        return []
    results = []
    # site uses #venkonten .vezone ul.genres li a in earlier file; fallback to .genres li a
    for a in soup.select("#venkonten .vezone ul.genres li a, div.genres li a, .genres li a"):
        results.append({
            "name": a.get_text(strip=True),
            "link": a.get("href")
        })
    save_json(results, "genrelist.json", OUT_GENRE)
    return results

# -- Jadwal rilis --
def scrape_jadwal():
    url = f"{BASE_URL}/jadwal-rilis/"
    soup = soup_from_url(url)
    if not soup:
        return {}
    jadwal = {}
    # files used div.jadwal-konten with h2 day and ul li entries
    for box in soup.select("div.jadwal-konten"):
        day_el = box.select_one("h2")
        day = day_el.get_text(strip=True) if day_el else "unknown"
        items = []
        for li in box.select("ul li"):
            a = li.select_one("a")
            if a and a.has_attr("href"):
                items.append({"title": a.get_text(strip=True), "link": a.get("href")})
        jadwal[day] = items
    save_json(jadwal, "jadwalrilis.json", OUT_JADWAL)
    return jadwal

# -- Anime detail + episodes list --
def scrape_anime_detail_by_slug(slug):
    url = f"{BASE_URL}/anime/{slug}/"
    soup = soup_from_url(url)
    if not soup:
        return None
    # Title: many variants exist; check common selectors
    title = None
    # try .infozin .infozingle p:first span pattern (from Next.js), then .jdlrx h1, then h1
    t = soup.select_one(".infozin .infozingle p:first-child span, .jdlrx h1, h1, .post-title")
    if t:
        title = t.get_text(strip=True).replace("Judul: ", "")
    # synopsis
    synopsis = None
    syn = soup.select_one(".sinopsis, .sinopc, .sinopc p, #venkonten .sinopsis, .entry-content .sinopsis")
    if syn:
        synopsis = syn.get_text("\n", strip=True)
    # poster
    poster = None
    pimg = soup.select_one(".detpost .thumb .thumbz img, .fotoanime img, .post img, meta[property='og:image']")
    if pimg:
        if pimg.name == "meta":
            poster = pimg.get("content")
        else:
            poster = pimg.get("src") or pimg.get("data-src")
    # genres: try mapGenres selector
    genres = [g.get_text(strip=True) for g in soup.select("#venkonten .vezone ul.genres li a, .infozingle a[href*='genres'], .genre-info a, .genres a")]
    # info fields: parse .infozin .infozingle p elements for Skor/Produser/Tipe/Status
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
    # episodes: prefer .episodelist second node (many mirrors use second)
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
    # fallback: try anchors containing '/episode/'
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
    save_json(data, f"{slug}.json", OUT_ANIME)
    return data

# -- Episode detail (embed + downloads) --
def scrape_episode_detail_by_slug(slug):
    url = f"{BASE_URL}/episode/{slug}/"
    soup = soup_from_url(url)
    if not soup:
        return None
    # title
    title_el = soup.select_one(".venutama .posttl, h1, .post-title")
    title = title_el.get_text(strip=True) if title_el else None
    # embed iframe: #pembed iframe or any iframe[src]
    iframe = soup.select_one("#pembed iframe, iframe[src], .player iframe")
    embed_url = iframe.get("src") if iframe and iframe.has_attr("src") else None
    # collect all iframe srcs
    embeds = [i.get("src") for i in soup.select("iframe[src]") if i and i.has_attr("src")]
    # downloads: .download a, .dlbutton a, .download ul li a
    downloads = []
    # many pages have <div class="download"> <ul> <li> ... <a> tags
    for container in soup.select(".download, .dlbutton, .downloadlinks"):
        for a in container.select("a[href]"):
            downloads.append({"host": a.get_text(strip=True), "link": a.get("href")})
    # also try specific list items
    for li in soup.select(".download ul li, .dowload-servers li"):
        qa = li.select_one("strong")
        quality = qa.get_text(strip=True) if qa else None
        links = []
        for a in li.select("a[href]"):
            links.append({"host": a.get_text(strip=True), "link": a.get("href")})
        if links:
            downloads.append({"quality": quality, "links": links})
    # try previous/next / anime reference
    flir_anchors = [a.get("href") for a in soup.select(".flir a[href]") if a and a.has_attr("href")]
    anime_url = None
    if flir_anchors:
        # usually first or second anchor points to anime
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
    save_json(data, f"{slug}.json", OUT_EPISODE)
    return data

# -- Run All flow --
def run_all():
    logger.info(">>> Starting scraping process")
    try:
        logger.info(">>> Scraping home (root)")
        scrape_home()
        
        logger.info(">>> Scraping ongoing pages (collect unique slugs)")
        ongoing = scrape_ongoing_pages()
        
        logger.info(">>> Scraping genre list")
        scrape_genrelist()
        
        logger.info(">>> Scraping jadwal rilis")
        scrape_jadwal()
        
        # gather slugs to process:
        slugs = set()
        # from ongoing
        for it in ongoing:
            if it.get("slug"):
                slugs.add(it["slug"])
        # from home (root) as well
        home_items = []
        hpath = OUT_HOME / "home.json"
        if hpath.exists():
            try:
                home_items = json.loads(hpath.read_text(encoding="utf-8"))
            except Exception:
                home_items = []
        for it in home_items:
            if isinstance(it, dict) and it.get("slug"):
                slugs.add(it["slug"])
        
        logger.info(f"Collected {len(slugs)} unique slugs. Starting detail scrape...")
        
        # scrape anime detail + episodes, then episode details
        ep_queue = set()
        i = 0
        slugs_list = sorted(slugs)
        
        for slug in slugs_list:
            i += 1
            try:
                logger.info(f"[{i}/{len(slugs_list)}] Scraping anime detail: {slug}")
                ad = scrape_anime_detail_by_slug(slug)
                if not ad:
                    continue
                # add episode slugs
                for ep in ad.get("episodes", []):
                    if ep.get("slug"):
                        ep_queue.add(ep["slug"])
                    else:
                        # maybe link is full url; derive slug
                        link = ep.get("link")
                        if link:
                            ep_queue.add(slug_from_url(link))
            except Exception as e:
                logger.error(f"ERROR scraping anime detail {slug}: {e}")
                logger.debug(traceback.format_exc())
        
        logger.info(f"Episode queue size: {len(ep_queue)}. Scraping episode details ...")
        ep_queue_list = sorted([s for s in ep_queue if s])
        j = 0
        
        for ep_slug in ep_queue_list:
            j += 1
            try:
                logger.info(f"[{j}/{len(ep_queue_list)}] Scraping episode: {ep_slug}")
                scrape_episode_detail_by_slug(ep_slug)
            except Exception as e:
                logger.error(f"ERROR scraping episode {ep_slug}: {e}")
                logger.debug(traceback.format_exc())
        
        logger.info(">>> ALL DONE")
    
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error in scraping process: {e}")
        logger.debug(traceback.format_exc())
    finally:
        # Clean up resources
        scraper_session.close()

# -------- Entry point --------
if __name__ == "__main__":
    # default: run full all
    run_all()
