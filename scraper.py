#!/usr/bin/env python3
# scraper_all.py
# Runs full scrape: home, ongoing (paged), genre list, jadwal, all anime details, all episodes details.
# BASE_URL hardcoded to otakudesu.best

import requests
from bs4 import BeautifulSoup
import time
import json
from pathlib import Path
import re
from urllib.parse import urljoin
import sys
import traceback

# -------- CONFIG --------
BASE_URL = "https://otakudesu.best"
RATE_LIMIT = 1.5         # seconds between requests (tweak if needed)
RETRIES = 3
TIMEOUT = 20

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}

# -------- Helpers --------
def fetch(url, retries=RETRIES, timeout=TIMEOUT):
    for attempt in range(1, retries+1):
        try:
            print(f"[GET] {url} (attempt {attempt})")
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            time.sleep(RATE_LIMIT)
            return r.text
        except Exception as e:
            print(f"  fetch error: {e}")
            if attempt == retries:
                print("  giving up:", url)
                return None
            time.sleep(1)
    return None

def soup_from_url(url):
    html = fetch(url)
    if not html:
        return None
    return BeautifulSoup(html, "html.parser")

def save_json(data, filename, folder):
    path = Path(folder) / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[saved] {path}")

def slug_from_url(url):
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
def scrape_ongoing_pages(max_pages=200):
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
    print(">>> Scraping home (root)")
    scrape_home()

    print(">>> Scraping ongoing pages (collect unique slugs)")
    ongoing = scrape_ongoing_pages()

    print(">>> Scraping genre list")
    scrape_genrelist()

    print(">>> Scraping jadwal rilis")
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

    print(f"Collected {len(slugs)} unique slugs. Starting detail scrape...")

    # scrape anime detail + episodes, then episode details
    ep_queue = set()
    i = 0
    for slug in sorted(slugs):
        i += 1
        try:
            print(f"[{i}/{len(slugs)}] Scraping anime detail: {slug}")
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
            print("ERROR scraping anime detail:", slug, e)
            traceback.print_exc()

    print(f"Episode queue size: {len(ep_queue)}. Scraping episode details ...")
    j = 0
    for ep_slug in sorted([s for s in ep_queue if s]):
        j += 1
        try:
            print(f"[{j}/{len(ep_queue)}] Scraping episode: {ep_slug}")
            scrape_episode_detail_by_slug(ep_slug)
        except Exception as e:
            print("ERROR scraping episode:", ep_slug, e)
            traceback.print_exc()

    print(">>> ALL DONE")

# -------- Entry point --------
if __name__ == "__main__":
    # default: run full all
    run_all()
