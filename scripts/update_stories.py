#!/usr/bin/env python3
"""Add Sean Krofssik's new Hartford Courant stories to site/stories.json.

Run by the GitHub Actions workflow every 6 hours. Reads only Sean's author page
on courant.com, keeps only https://www.courant.com/YYYY/MM/DD/ links, strips HTML
from titles, and leaves the file alone if nothing is found.

Every NEW story is opened and checked before it is added: Sean must be named as
author and the page must not carry a wire/syndication credit (AP, NYT, etc.).
A story that fails, or can't be checked, is skipped and retried on the next run.
Stories already in stories.json (and the courant.com stories built into index.html)
are audited the same way, a batch per run. A stored story that is clearly not Sean's
is removed from stories.json; ones that pass are remembered in "verified" so they are
not fetched again. If a page can't be read, nothing is removed.
"""
import html, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone

SOURCE = "https://www.courant.com/author/sean-krofssik/"
PAGES = 12
MAX_STORIES = 600
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "stories.json")
INDEX = os.path.join(os.path.dirname(__file__), "..", "site", "index.html")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 seankrofssik.com-updater")
URL_OK = re.compile(r"^https://www\.courant\.com/(\d{4})/(\d{2})/(\d{2})/[a-z0-9\-]+/?$")

# URLs to never carry (removed by hand), and URLs to accept without checking.
EXCLUDE = {
    "https://www.courant.com/2026/10/16/katie-zacharia-is-out-after-5-days-as-white-house-press-secretary/",
}
ALLOW = set()
MAX_VERIFY = 60  # article pages opened per run
MAX_REMOVE_SHARE = 0.2  # never remove more than this share of stored stories in one run

WIRE_NAMES = (r"associated press|new york times|washington post|los angeles times|reuters|bloomberg|"
              r"tribune news service|tribune content agency|usa today|states newsroom|cnn|npr|"
              r"nbc news|abc news|cbs news|bay state banner")
WIRE_HEAD = re.compile(r"\(AP\)|\bAP\b|\b(?:%s)\b" % WIRE_NAMES, re.I)
WIRE_TAIL = re.compile(r"(?:©|\(c\)|copyright|distributed by|provided by|syndicated|\bTNS\b)[^.]{0,60}?(?:%s)|"
                       r"\b(?:%s)\b[^.]{0,40}?(?:©|copyright|all rights reserved)" % (WIRE_NAMES, WIRE_NAMES), re.I)

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

def _text(frag):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", frag))).strip()

def _walk_authors(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k.lower() in ("author", "creator"):
                for a in (v if isinstance(v, list) else [v]):
                    out.append(a.get("name", "") if isinstance(a, dict) else str(a))
            else:
                _walk_authors(v, out)
    elif isinstance(node, list):
        for n in node:
            _walk_authors(n, out)

def authors(page):
    """Author strings from meta tags, JSON-LD and byline elements."""
    out = []
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        n = re.search(r'(?:name|property)\s*=\s*"([^"]+)"', tag, re.I)
        c = re.search(r'content\s*=\s*"([^"]*)"', tag, re.I)
        if n and c and n.group(1).lower() in ("author", "article:author", "parsely-author",
                                              "sailthru.author", "dc.creator", "byl"):
            out.append(html.unescape(c.group(1)))
    for blob in re.findall(r"<script[^>]+ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try: _walk_authors(json.loads(blob), out)
        except Exception: pass
    for frag in re.findall(r'class="[^"]*(?:byline|article-author|author-name)[^"]*"[^>]*>(.{0,300}?)</', page, re.S | re.I):
        out.append(_text(frag))
    return [a for a in (x.strip() for x in out) if a]

def verify(page):
    """Return (ok, reason) for one article page."""
    names = authors(page)
    if not names:
        return False, "no author info found on page"
    joined = " | ".join(names)
    if "krofssik" not in joined.lower():
        return False, f"author is not Sean ({joined[:80]})"
    if WIRE_HEAD.search(joined):
        return False, f"wire/syndication credit in byline ({joined[:80]})"
    m = re.search(r"<article\b[^>]*>(.*?)</article>", page, re.S | re.I)
    body = _text(re.sub(r"<(script|style)\b.*?</\1>", " ", m.group(1) if m else page, flags=re.S | re.I))
    if WIRE_HEAD.search(body[:200]):
        return False, "wire credit at top of article"
    if WIRE_TAIL.search(body[-400:]):
        return False, "wire/syndication credit at end of article"
    return True, "ok"

def check(url):
    """Fetch and verify one article. Returns (status, reason): ok / bad / unknown."""
    page = fetch(url)
    time.sleep(0.8)
    if not page:
        return "unknown", "could not fetch article"
    ok, why = verify(page)
    if ok:
        return "ok", why
    # Only treat as a definite "not Sean's" when the page had author info.
    return ("unknown" if why.startswith("no author info") else "bad"), why

def builtin_urls():
    """courant.com links built into index.html (report-only; editing that script would change the CSP hash)."""
    try:
        page = open(INDEX, encoding="utf-8").read()
    except Exception:
        return []
    m = re.search(r"const clips = \[(.*?)\n\]\.sort", page, re.S)
    return sorted(set(u for u in re.findall(r'https://www\.courant\.com/\d{4}/\d{2}/\d{2}/[a-z0-9\-]+/?', m.group(1) if m else "")))

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
    try:
        data = json.load(open(OUT, encoding="utf-8"))
        existing = data.get("stories", []) if isinstance(data, dict) else []
        verified = set(data.get("verified", [])) if isinstance(data, dict) else set()
    except Exception:
        existing, verified = [], set()
    if not found and not existing:
        print("no stories found this run; stories.json left unchanged"); return 0
    by_url = {s["u"]: s for s in existing if isinstance(s, dict) and s.get("u") and s["u"] not in EXCLUDE}
    removed_urls = {s["u"] for s in existing if isinstance(s, dict) and s.get("u") and s["u"] in EXCLUDE}
    budget = MAX_VERIFY
    added = skipped = 0
    unknown_streak_only = True  # no successful read yet this run
    markup_alarm = False

    def run_check(u):
        nonlocal budget, unknown_streak_only
        budget -= 1
        st, why = check(u)
        if st == "ok":
            unknown_streak_only = False
        return st, why

    # 1) new stories from the author page: must pass to be added
    for s in found:
        u = s["u"]
        if u in by_url or u in EXCLUDE:
            continue
        if u in ALLOW or test:
            by_url[u] = s; verified.add(u); added += 1; continue
        if budget <= 0:
            print(f"verify limit reached; {u} waits for next run"); continue
        st, why = run_check(u)
        if st == "ok":
            by_url[u] = s; verified.add(u); added += 1
        else:
            skipped += 1; print(f"SKIPPED {u}: {why}")

    # 2) audit stories already stored (newest first); remove clear non-Sean stories
    to_remove = []
    unknown = 0
    if not test:
        for s in sorted(by_url.values(), key=lambda x: x["d"], reverse=True):
            u = s["u"]
            if u in verified or u in ALLOW or budget <= 0:
                continue
            if unknown >= 5 and unknown_streak_only:
                markup_alarm = True; break
            st, why = run_check(u)
            if st == "ok":
                verified.add(u)
            elif st == "bad":
                to_remove.append(u); print(f"NOT SEAN'S, removing {u}: {why}")
            else:
                unknown += 1; print(f"UNCHECKED {u}: {why}")
        if markup_alarm:
            print("STOPPED AUDIT: could not read author info on 5 pages in a row; Courant page markup may have changed. Nothing removed for that reason.")
        if to_remove and len(to_remove) > MAX_REMOVE_SHARE * max(len(by_url), 1):
            print(f"REFUSING to remove {len(to_remove)} stories (over {int(MAX_REMOVE_SHARE*100)}% of {len(by_url)}); check the rules"); to_remove = []
        for u in to_remove:
            by_url.pop(u, None); verified.discard(u); removed_urls.add(u)

        # 3) built-in stories in index.html: report only
        for u in builtin_urls():
            if u in verified or u in by_url or budget <= 0 or markup_alarm:
                continue
            st, why = run_check(u)
            if st == "ok": verified.add(u)
            elif st == "bad": print(f"BUILT-IN NOT SEAN'S (edit index.html by hand and update the CSP hash): {u}: {why}")
            else: print(f"BUILT-IN UNCHECKED {u}: {why}")

    removed = len(removed_urls)
    new_verified = sorted(v for v in verified if v in by_url or v in builtin_urls())
    old_verified = sorted(set(data.get("verified", []))) if isinstance(data, dict) else []
    if not added and not removed and new_verified == old_verified:
        print(f"checked {len(found)} stories, nothing new ({skipped} skipped)"); return 0
    stories = sorted(by_url.values(), key=lambda s: s["d"], reverse=True)[:MAX_STORIES]
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SOURCE,
                   "stories": stories, "verified": new_verified}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"added {added} new {'story' if added == 1 else 'stories'}, removed {removed}, skipped {skipped}; total {len(stories)}, verified {len(new_verified)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
