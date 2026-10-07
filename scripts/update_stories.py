#!/usr/bin/env python3
"""Add Sean Krofssik's new Hartford Courant stories to site/stories.json.

Run by the GitHub Actions workflow every 6 hours. Reads only Sean's author page
on courant.com, keeps only https://www.courant.com/YYYY/MM/DD/ links, strips HTML
from titles, never removes stories, and leaves the file alone if nothing is found.
"""
import html, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone

SOURCE = "https://www.courant.com/author/sean-krofssik/"
PAGES = 3
MAX_STORIES = 600
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "stories.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 seankrofssik.com-updater")
URL_OK = re.compile(r"^https://www\.courant\.com/(\d{4})/(\d{2})/(\d{2})/[a-z0-9\-]+/?$")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                print(f"fetch failed {url} (HTTP {r.status})"); return None
            body = r.read(5 * 1024 * 1024 + 1)
            if len(body) > 5 * 1024 * 1024:
                print(f"page too large: {url}"); return None
            return body.decode("utf-8", "replace")
    except Exception as e:
        print(f"fetch failed {url}: {e}"); return None

def clean(s):
    s = html.unescape(re.sub(r"<[^>]*>", "", s))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:217] + "..." if len(s) > 220 else s

def section(classes, title):
    c, t = f" {classes.lower()} ", title.lower()
    if re.search(r"category-(sports|high-school-sports|uconn)\b", c): return "sports"
    if re.search(r"category-(crime|public-safety|courts|police|breaking-news|transportation|traffic|weather)\b", c) or \
       re.search(r"\b(police|court|charged|charges|arrest|crash|killed|shooting|dui|trooper|highway|lane|flood\w*|wrong.way|ice detention|sentenced)\b", t): return "safety"
    if re.search(r"category-(health|medical|mental-health)\b", c) or \
       re.search(r"\b(hospital|doctors?|health|patients|cancer|nurses?|overdose|shelter|therapy|medical)\b", t): return "health"
    if re.search(r"category-(business|real-estate|food-drink|restaurants)\b", c) or \
       re.search(r"\b(restaurant|store|business|mall|shop|opens|expanding|closing|tipping|market|bakery|diner)\b", t): return "biz"
    return "com"

def parse(page):
    out = []
    for attrs, inner in re.findall(r"<article\b([^>]*)>(.*?)</article>", page, re.S | re.I):
        m = re.search(r'<a\s+class="article-title"\s+href="([^"]+)"[^>]*>(.*?)</a>', inner, re.S | re.I)
        if not m: continue
        url = html.unescape(m.group(1))
        d = URL_OK.match(url)
        if not d: continue
        title = clean(m.group(2))
        if not title: continue
        cm = re.search(r'class="([^"]*)"', attrs, re.I)
        out.append({"s": section(cm.group(1) if cm else "", title), "d": f"{d[1]}-{d[2]}-{d[3]}", "t": title, "u": url})
    return out

def main():
    test = os.environ.get("SK_TEST_HTML")
    found = []
    if test:
        found = parse(open(test, encoding="utf-8").read())
    else:
        for p in range(1, PAGES + 1):
            page = fetch(SOURCE if p == 1 else f"{SOURCE}page/{p}/")
            if not page: break
            items = parse(page)
            if not items: break
            found += items
            time.sleep(0.8)
    if not found:
        print("no stories found this run; stories.json left unchanged"); return 0
    try:
        data = json.load(open(OUT, encoding="utf-8"))
        existing = data.get("stories", []) if isinstance(data, dict) else []
    except Exception:
        existing = []
    by_url = {s["u"]: s for s in existing if isinstance(s, dict) and s.get("u")}
    added = 0
    for s in found:
        if s["u"] not in by_url:
            by_url[s["u"]] = s; added += 1
    if not added:
        print(f"checked {len(found)} stories, nothing new"); return 0
    stories = sorted(by_url.values(), key=lambda s: s["d"], reverse=True)[:MAX_STORIES]
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SOURCE, "stories": stories},
                  f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"added {added} new {'story' if added == 1 else 'stories'}; total {len(stories)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
