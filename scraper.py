import requests
from bs4 import BeautifulSoup
import json
import re
import os
import argparse
import time

BASE_URL = "https://otakudesu.best"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}


def fetch(url, retries=3, delay=3):
    for i in range(retries):
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code == 200:
                return res.text
        except Exception as e:
            print(f"Fetch error: {e}, retry {i+1}/{retries}")
        time.sleep(delay)
    return None


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip() if text else ""


def parse_home(page=1):
    url = f"{BASE_URL}/ongoing-anime/page/{page}/" if page > 1 else f"{BASE_URL}/ongoing-anime/"
    html = fetch(url)
    if not html:
        return {"error": "gagal fetch home"}
    soup = BeautifulSoup(html, "html.parser")
    data = []
    for li in soup.select(".venz ul li"):
        title = clean_text(li.select_one("h2").get_text()) if li.select_one("h2") else ""
        link = li.select_one("a")["href"] if li.select_one("a") else ""
        thumb = li.select_one("img")["src"] if li.select_one("img") else ""
        eps = clean_text(li.select_one(".epz").get_text()) if li.select_one(".epz") else ""
        date = clean_text(li.select_one(".epztipe").get_text()) if li.select_one(".epztipe") else ""
        data.append({
            "title": title,
            "slug": re.sub(r"^https://otakudesu\.best/anime/", "", link).strip("/"),
            "link": link,
            "thumbnail": thumb,
            "episode": eps,
            "status": date
        })
    return {"page": page, "results": data}


def parse_anime(slug):
    url = f"{BASE_URL}/anime/{slug}/"
    html = fetch(url)
    if not html:
        return {"error": "gagal fetch anime"}
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.select_one(".jdlrx h1").get_text()) if soup.select_one(".jdlrx h1") else ""
    thumb = soup.select_one(".fotoanime img")["src"] if soup.select_one(".fotoanime img") else ""
    sinopsis = clean_text(soup.select_one(".sinopc").get_text()) if soup.select_one(".sinopc") else ""
    genres = [a.get_text() for a in soup.select(".infozingle span a")]
    episodes = []
    for li in soup.select(".episodelist ul li"):
        eps_a = li.select_one("a")
        if eps_a:
            episodes.append({
                "title": clean_text(eps_a.get_text()),
                "link": eps_a["href"],
                "slug": eps_a["href"].rstrip("/").split("/")[-1]
            })
    return {
        "title": title,
        "thumbnail": thumb,
        "synopsis": sinopsis,
        "genres": genres,
        "episodes": episodes
    }


def parse_episode(slug):
    url = f"{BASE_URL}/episode/{slug}/"
    html = fetch(url)
    if not html:
        return {"error": "gagal fetch episode"}
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.select_one(".posttl").get_text()) if soup.select_one(".posttl") else ""
    stream_url = soup.select_one("#pembed iframe")["src"] if soup.select_one("#pembed iframe") else ""
    downloads = []
    for a in soup.select(".download > ul > li a"):
        downloads.append({"host": a.get_text(), "link": a["href"]})
    return {
        "title": title,
        "stream_url": stream_url,
        "downloads": downloads
    }


def parse_batch(slug):
    url = f"{BASE_URL}/batch/{slug}/"
    html = fetch(url)
    if not html:
        return {"error": "gagal fetch batch"}
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.select_one(".jdlrx h1").get_text()) if soup.select_one(".jdlrx h1") else ""
    downloads = []
    for li in soup.select(".batchlink ul li"):
        for a in li.select("a"):
            downloads.append({
                "quality": clean_text(li.get_text().split()[0]),
                "host": a.get_text(),
                "link": a["href"]
            })
    return {"title": title, "downloads": downloads}


def save_json(name, data):
    os.makedirs("outputs", exist_ok=True)
    path = os.path.join("outputs", f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved {path}")


def run_all():
    page = 1
    all_anime = []
    while True:
        home = parse_home(page=page)
        if "results" not in home or not home["results"]:
            break
        save_json(f"home_p{page}", home)
        all_anime.extend(home["results"])
        page += 1

    for anime in all_anime:
        slug = anime["slug"]
        detail = parse_anime(slug)
        save_json(f"anime_{slug}", detail)

        # batch jika ada
        batch = parse_batch(slug)
        if "downloads" in batch and batch["downloads"]:
            save_json(f"batch_{slug}", batch)

        # episodes
        for ep in detail.get("episodes", []):
            epslug = ep["slug"]
            epdetail = parse_episode(epslug)
            save_json(f"episode_{epslug}", epdetail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["home", "anime", "episode", "batch", "all"])
    parser.add_argument("--slug", help="slug anime/episode")
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()

    if args.mode == "home":
        data = parse_home(page=args.page)
        save_json(f"home_p{args.page}", data)
    elif args.mode == "anime":
        if not args.slug:
            print("butuh --slug")
            return
        data = parse_anime(args.slug)
        save_json(f"anime_{args.slug}", data)
    elif args.mode == "episode":
        if not args.slug:
            print("butuh --slug")
            return
        data = parse_episode(args.slug)
        save_json(f"episode_{args.slug}", data)
    elif args.mode == "batch":
        if not args.slug:
            print("butuh --slug")
            return
        data = parse_batch(args.slug)
        save_json(f"batch_{args.slug}", data)
    elif args.mode == "all":
        run_all()


if __name__ == "__main__":
    main()
