#!/usr/bin/env python3
"""Make Sean's stories readable by search engines and AI agents.

Runs in the GitHub Actions workflow right before the site is published, and
only changes the copy that gets published (nothing is committed back).

It merges the stories built into index.html with site/stories.json, then writes:
  - the story cards into index.html as plain HTML (the page's script replaces
    them with the tabbed view, so visitors see no difference)
  - schema.org JSON-LD (Person, ProfilePage, list of articles) into index.html
  - feed.xml   RSS feed of the newest stories
  - llms.txt   plain-text summary for AI agents
  - sitemap.xml with an up-to-date lastmod
  - one page per topic (/courts/, /transportation/, ...) listing matching stories

Only headlines, dates, outlet names and links are published. No article text.
"""
import html, json, os, re, sys
from datetime import datetime, timezone
from email.utils import format_datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")
SITE = "https://seankrofssik.com/"
COURANT = "Hartford Courant"
SECTIONS = {"com": "Community", "biz": "Business", "safety": "Justice & Safety", "health": "Health", "sports": "Sports"}
GNEWS = "https://news.google.com/rss/articles/{}?oc=5"
DIRECT = re.compile(r"^https://(www\.courant\.com|www\.gaylord\.org)/")
FEED_ITEMS = 50

def esc(s):
    return html.escape(str(s), quote=True)

def key(t):
    return re.sub(r"[^a-z0-9]", "", str(t).lower())[:40]

def built_in(page):
    """Read the stories array from the page script without running it."""
    m = re.search(r"const clips = \[(.*?)\n\]\.sort", page, re.S)
    if not m:
        sys.exit("build_seo: could not find the stories list in index.html")
    out = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        if line.startswith('{"'):
            out.append(json.loads(line))
            continue
        item = {}
        for k in ("s", "d", "t", "o"):
            f = re.search(r'\b%s:"([^"]*)"' % k, line)
            if f:
                item[k] = f.group(1)
        u = re.search(r'\bu:"([^"]*)"', line)
        g = re.search(r'\bu:G\("([^"]*)"\)', line)
        item["u"] = u.group(1) if u else (GNEWS.format(g.group(1)) if g else "")
        if item.get("t") and item.get("d") and item["u"]:
            out.append(item)
    return out

def from_json(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for s in (data.get("stories") or [])[:1000]:
        if not isinstance(s, dict):
            continue
        t, d, u = s.get("t"), s.get("d"), s.get("u")
        if not all(isinstance(x, str) for x in (t, d, u)):
            continue
        if not re.match(r"^https://www\.courant\.com/\d{4}/\d{2}/\d{2}/", u) or not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            continue
        out.append({"s": s.get("s") if s.get("s") in SECTIONS else "com", "d": d, "t": t[:240], "u": u})
    return out

def merge(a, b):
    """One entry per story. A direct courant.com link wins over a Google News link."""
    by_key = {}
    for s in a + b:
        k = key(s["t"])
        old = by_key.get(k)
        if old is None:
            by_key[k] = dict(s)
        elif not DIRECT.match(old["u"]) and DIRECT.match(s["u"]):
            old["u"] = s["u"]
    seen, out = set(), []
    for s in sorted(by_key.values(), key=lambda s: s["d"], reverse=True):
        if s["u"] in seen:
            continue
        seen.add(s["u"]); out.append(s)
    return out

def outlet(s):
    o = s.get("o")
    return o if o and "Yahoo" not in o else COURANT

def nice_date(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%B %-d, %Y")

def cards_html(stories):
    rows = []
    for s in stories:
        rows.append(
            '<a class="card" href="%s" target="_blank" rel="noopener noreferrer">'
            '<span class="out">%s</span><h3>%s</h3><time datetime="%s">%s</time>'
            '<span class="go">Read on <span aria-hidden="true">&rarr;</span></span></a>'
            % (esc(s["u"]), esc(outlet(s)), esc(s["t"]), s["d"], nice_date(s["d"])))
    return '<div class="cards">' + "\n".join(rows) + "</div>"

def jsonld(stories, today):
    person = {
        "@type": "Person", "@id": SITE + "#sean",
        "name": "Sean Krofssik", "givenName": "Sean", "familyName": "Krofssik",
        "jobTitle": "Staff Reporter",
        "description": "Staff reporter at the Hartford Courant covering breaking news, courts, public safety and local business in Connecticut. Previously a sports reporter at the Record-Journal in Meriden for 19 years.",
        "worksFor": {"@type": "NewsMediaOrganization", "name": COURANT, "url": "https://www.courant.com/"},
        "alumniOf": {"@type": "CollegeOrUniversity", "name": "Southern Connecticut State University"},
        "homeLocation": {"@type": "Place", "name": "Waterbury, Connecticut"},
        "knowsAbout": ["Breaking news", "Courts", "Public safety", "Transportation", "Local business", "High school sports", "Connecticut"],
        "award": "First place, Sports News, Connecticut SPJ Excellence in Journalism Awards (2013 contest year)",
        "url": SITE, "image": SITE + "og-image.png",
        "sameAs": ["https://x.com/SKrofssik", "https://muckrack.com/sean-krofssik", "https://www.courant.com/author/sean-krofssik/"],
    }
    articles = [s for s in stories if DIRECT.match(s["u"])]
    items = [{
        "@type": "ListItem", "position": i + 1,
        "item": {"@type": "NewsArticle", "headline": s["t"][:110], "url": s["u"], "datePublished": s["d"],
                 "author": {"@id": SITE + "#sean"}, "publisher": {"@type": "NewsMediaOrganization", "name": outlet(s)}},
    } for i, s in enumerate(articles)]
    graph = [
        {"@type": "WebSite", "@id": SITE + "#site", "url": SITE, "name": "Sean Krofssik", "inLanguage": "en-US"},
        {"@type": "ProfilePage", "@id": SITE + "#page", "url": SITE, "name": "Sean Krofssik | Reporter, Hartford Courant",
         "isPartOf": {"@id": SITE + "#site"}, "mainEntity": {"@id": SITE + "#sean"}, "dateModified": today,
         "hasPart": {"@id": SITE + "#stories"}},
        person,
        {"@type": "ItemList", "@id": SITE + "#stories", "name": "Stories by Sean Krofssik",
         "itemListOrder": "https://schema.org/ItemListOrderDescending", "numberOfItems": len(items), "itemListElement": items},
    ]
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, separators=(",", ":"))
    return '<script type="application/ld+json">' + text.replace("</", "<\\/") + "</script>"

def feed_xml(stories, now):
    items = []
    for s in stories[:FEED_ITEMS]:
        pub = format_datetime(datetime.strptime(s["d"] + " 12:00", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc))
        items.append(
            "<item><title>%s</title><link>%s</link><guid isPermaLink=\"true\">%s</guid><pubDate>%s</pubDate>"
            "<category>%s</category><source url=\"%sfeed.xml\">%s</source></item>"
            % (esc(s["t"]), esc(s["u"]), esc(s["u"]), pub, esc(SECTIONS.get(s.get("s"), "Community")), SITE, esc(outlet(s))))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            "<title>Sean Krofssik: stories</title>\n<link>%s</link>\n"
            '<atom:link href="%sfeed.xml" rel="self" type="application/rss+xml"/>\n'
            "<description>Headlines and links to stories by Sean Krofssik, reporter at the Hartford Courant.</description>\n"
            "<language>en-us</language>\n<lastBuildDate>%s</lastBuildDate>\n%s\n</channel>\n</rss>\n"
            % (SITE, SITE, format_datetime(now), "\n".join(items)))

def llms_txt(stories, today, groups=None):
    lines = [
        "# Sean Krofssik",
        "",
        "> Sean Krofssik is a staff reporter at the Hartford Courant in Connecticut. He covers breaking news, courts, "
        "public safety, transportation and local business. Before joining the Courant in 2024 he spent 19 years as a "
        "sports reporter at the Record-Journal in Meriden.",
        "",
        "This file lists his published stories with links. Headlines belong to their publishers; follow the links to read the stories.",
        "",
        "## About",
        "- Role: Staff reporter, Hartford Courant (freelance from 2024, then staff)",
        "- Earlier: Sports reporter, Record-Journal, Meriden, 2004-2023; sports writer, The Southington Citizen, 2004-2007",
        "- Based in: Waterbury area, Connecticut",
        "- Education: Journalism, Southern Connecticut State University",
        "- Honors: First place, Sports News, Connecticut SPJ Excellence in Journalism Awards (2013 contest year); studio guest on CPTV's GameTime (2016)",
        "- Covers: Hartford, Waterbury, Meriden, Wallingford, Southington, Cheshire and towns across Connecticut",
        "",
        "## Links",
        "- [Website](%s): bio, career and full story list" % SITE,
        "- [Hartford Courant author page](https://www.courant.com/author/sean-krofssik/): newest stories",
        "- [Muck Rack](https://muckrack.com/sean-krofssik): portfolio",
        "- [X @SKrofssik](https://x.com/SKrofssik): best way to send a story idea or tip",
        "- [RSS feed](%sfeed.xml) and [JSON list](%sstories.json) of stories" % (SITE, SITE),
        "",
    ]
    if groups:
        lines += ["## Topics"] + ["- [%s](%s%s/): %d stories" % (t["h1"], SITE, t["slug"], len(groups[t["slug"]]))
                                  for t in TOPICS if t["slug"] in groups] + [""]
    lines += ["## Stories (newest first, updated %s)" % today]
    for s in stories:
        lines.append("- [%s](%s): %s, %s, %s" % (s["t"].replace("[", "(").replace("]", ")"), s["u"], outlet(s),
                                                 SECTIONS.get(s.get("s"), "Community"), nice_date(s["d"])))
    return "\n".join(lines) + "\n"

def sitemap(today, slugs=()):
    urls = [SITE] + [SITE + s + "/" for s in slugs]
    rows = "".join("  <url><loc>%s</loc><lastmod>%s</lastmod><changefreq>daily</changefreq></url>\n" % (u, today) for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + rows + "</urlset>\n")

# ---------- Topic pages ----------
# Each topic gets its own page at /<slug>/ listing the matching stories.
# A story can be on more than one topic page.
TOPICS = [
    {"slug": "courts", "nav": "Courts & crime",
     "h1": "Connecticut courts, crime and police",
     "title": "Connecticut Courts, Crime and Police Stories | Sean Krofssik",
     "desc": "Stories by Hartford Courant reporter Sean Krofssik on Connecticut courts, arrests, crime and police.",
     "intro": "I report on arrests, court cases and police across Connecticut for the Hartford Courant. These are those stories, newest first.",
     "re": r"\b(arrest\w*|charged|charges|convict\w*|appeal|courts?|police|officers?|shooting|shot|suspect|stabb\w*|sentenc\w*|DUI|hit-and-run|attorney|corruption|cockfighting|lawsuit|judge|trial|gun)\b",
     "case_re": r"\bICE\b"},
    {"slug": "transportation", "nav": "Roads & traffic",
     "h1": "Connecticut roads, highways and traffic",
     "title": "Connecticut Roads, Highways and Traffic Stories | Sean Krofssik",
     "desc": "Stories by Hartford Courant reporter Sean Krofssik on Connecticut highways, CTDOT projects, lane closures, crashes and road safety.",
     "intro": "Highway projects, lane closures, crashes and the push for safer roads. I cover a lot of transportation news for the Hartford Courant.",
     "re": r"\b(highways?|I-\d+|exits?|lanes?|traffic|CTDOT|DOT|bridges?|intersections?|roads?|roadways?|wrong[- ]way|driv(ing|ers?)|crash(es)?|rail|speed cameras|ferry|pedestrians?|motorcycle|transportation|interchange|detours?|motorists)\b"},
    {"slug": "fires-floods", "nav": "Fires & floods",
     "h1": "Fires, floods and emergencies in Connecticut",
     "title": "Connecticut Fires, Floods and Emergencies | Sean Krofssik",
     "desc": "Stories by Hartford Courant reporter Sean Krofssik on fires, flash flooding, rescues and the firefighters who respond across Connecticut.",
     "intro": "Fires, flash floods, rescues and the volunteer and career firefighters who respond to them.",
     "re": r"\b(fires?|firefighters?|firehouse|flood\w*|rescues?|displaced|rain bomb|three-alarm|smoke)\b"},
    {"slug": "business", "nav": "Business", "section": "biz",
     "h1": "Connecticut business, restaurants and shopping",
     "title": "Connecticut Business, Restaurant and Shopping Stories | Sean Krofssik",
     "desc": "Stories by Hartford Courant reporter Sean Krofssik on new restaurants, shops, malls and family-owned businesses across Connecticut.",
     "intro": "New restaurants, shops opening and closing, and family businesses passed down to the next generation.",
     "re": r"\b(restaurants?|cafe|bakery|diner|stores?|shops?|shoppers|mall|business(es)?|chains?|grocery|company|boutique|retailer|menus?|downtown|storeowner|headquarters|winery)\b"},
    {"slug": "health", "nav": "Health", "section": "health",
     "h1": "Health and hospitals in Connecticut",
     "title": "Connecticut Health and Hospital Stories | Sean Krofssik",
     "desc": "Stories by Hartford Courant reporter Sean Krofssik on Connecticut hospitals, doctors, patients, researchers and public health.",
     "intro": "Hospitals, doctors, researchers and patients in Connecticut, and the groups working to help people.",
     "re": r"\b(health|hospitals?|hospitalized|doctors?|patients?|cancer|nurses?|overdose|mental|medical|rehabilitation|shelter|therapy|surgery)\b"},
    {"slug": "community", "nav": "Community", "section": "com", "fallback": True,
     "h1": "Connecticut people and communities",
     "title": "Connecticut People and Community Stories | Sean Krofssik",
     "desc": "Stories by Hartford Courant reporter Sean Krofssik on the people, events and local history of Connecticut towns.",
     "intro": "People, events and local history from towns across Connecticut.",
     "re": None},
    {"slug": "sports", "nav": "Sports", "section": "sports",
     "h1": "Connecticut sports",
     "title": "Connecticut Sports Stories | Sean Krofssik",
     "desc": "Sports stories by Sean Krofssik, who covered high school and community sports for the Record-Journal in Meriden for 19 years.",
     "intro": "I spent 19 years covering high school and community sports for the Record-Journal in Meriden. These are the sports stories collected on this site.",
     "re": r"\b(sports?|softball|cyclist|fish|stadium|pickleball|NHL|swords)\b"},
]
MIN_TOPIC = 5

def sort_topics(stories):
    out = {t["slug"]: [] for t in TOPICS}
    for s in stories:
        hit = False
        for t in TOPICS:
            if t.get("fallback"):
                continue
            m = (t.get("section") and s.get("s") == t["section"]) or \
                (t["re"] and re.search(t["re"], s["t"], re.I)) or \
                (t.get("case_re") and re.search(t["case_re"], s["t"]))
            if m:
                out[t["slug"]].append(s); hit = True
        fb = [t for t in TOPICS if t.get("fallback")][0]
        if not hit or s.get("s") == fb.get("section"):
            out[fb["slug"]].append(s)
    return {k: v for k, v in out.items() if len(v) >= MIN_TOPIC}

TOPIC_CSS = (".topics{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;margin:26px auto 0;max-width:840px}"
             ".topics .lbl{flex-basis:100%;text-align:center;font-family:var(--cond);font-weight:600;letter-spacing:.1em;text-transform:uppercase;font-size:15px;color:var(--ink-3)}"
             ".topics a{--c:#0F6B72;display:inline-flex;align-items:center;gap:8px;min-height:44px;border:1.5px solid var(--line);border-bottom-width:5px;border-radius:8px;"
             "padding:8px 15px 6px;text-decoration:none;font-weight:600;font-size:16px;color:var(--ink);background:var(--paper);"
             "transition:transform .08s ease,border-bottom-width .08s ease,background .15s,color .15s}"
             ".topics a:nth-of-type(5n+2){--c:#E4572E}.topics a:nth-of-type(5n+3){--c:#F2B134}.topics a:nth-of-type(5n+4){--c:#2E86DE}.topics a:nth-of-type(5n){--c:#6AB04C}"
             ".topics a:hover{transform:translateY(-2px)}"
             ".topics a:active{transform:translateY(3px);border-bottom-width:2px;background:var(--c);color:#fff}"
             ".topics a:nth-of-type(5n+3):active{color:var(--ink)}"
             ".topics a .n{font-family:var(--mono);font-size:12px;font-weight:400;color:var(--ink-3)}"
             ".topics a:active .n{color:inherit}"
             ".topics a[aria-current]{background:#000;color:#fff;border-color:#000;border-bottom-color:#444}"
             ".topics a[aria-current] .n{color:#CFCFCF}"
             "@media (prefers-reduced-motion: reduce){.topics a{transition:none}}")

def topics_nav(groups, current=None, label="Browse by topic"):
    links = []
    for t in TOPICS:
        if t["slug"] not in groups:
            continue
        cur = ' aria-current="page"' if t["slug"] == current else ""
        links.append('<a href="/%s/"%s>%s <span class="n">%d</span></a>' % (t["slug"], cur, esc(t["nav"]), len(groups[t["slug"]])))
    return '<nav class="topics" aria-label="Story topics"><span class="lbl">%s</span>%s</nav>' % (label, "".join(links))

BEACON = ('<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" '
          "data-cf-beacon='{\"token\": \"5277b77fd1b84ae89d5bdb1a8dedf65e\"}'></script>")
TOPIC_CSP = ("default-src 'none'; script-src https://static.cloudflareinsights.com; style-src 'unsafe-inline' https://fonts.googleapis.com; "
             "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src https://cloudflareinsights.com; "
             "base-uri 'none'; form-action 'none'; upgrade-insecure-requests")

def topic_page(t, stories, groups, page_src, today):
    style = re.search(r"<style>(.*?)</style>", page_src, re.S).group(1)
    fonts = re.search(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com/css2[^"]*">', page_src).group(0)
    url = SITE + t["slug"] + "/"
    direct = [s for s in stories if DIRECT.match(s["u"])]
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "@id": url + "#page", "url": url, "name": t["title"], "description": t["desc"],
         "isPartOf": {"@id": SITE + "#site"}, "about": {"@id": SITE + "#sean"}, "dateModified": today,
         "breadcrumb": {"@id": url + "#crumbs"}, "mainEntity": {"@id": url + "#list"}},
        {"@type": "BreadcrumbList", "@id": url + "#crumbs", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Sean Krofssik", "item": SITE},
            {"@type": "ListItem", "position": 2, "name": t["h1"], "item": url}]},
        {"@type": "ItemList", "@id": url + "#list", "numberOfItems": len(direct),
         "itemListElement": [{"@type": "ListItem", "position": i + 1,
                              "item": {"@type": "NewsArticle", "headline": s["t"][:110], "url": s["u"], "datePublished": s["d"],
                                       "author": {"@type": "Person", "@id": SITE + "#sean", "name": "Sean Krofssik", "url": SITE},
                                       "publisher": {"@type": "NewsMediaOrganization", "name": outlet(s)}}}
                             for i, s in enumerate(direct)]},
    ]}
    ldtxt = json.dumps(ld, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    extra = (".top .wrap{min-height:64px}.home-link{color:#fff;text-decoration:none;font-weight:600;font-size:16px;"
             "padding:8px 12px;border:1px solid #666;border-radius:4px;white-space:nowrap}.home-link:hover{background:#222}"
             ".crumbs{margin-top:22px;font-size:15px;color:var(--ink-3)}.crumbs a{color:var(--ink-3)}"
             ".title-box p{max-width:62ch;margin-inline:auto}" + TOPIC_CSS)
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="%(csp)s">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<link rel="canonical" href="%(url)s">
<meta name="author" content="Sean Krofssik">
<meta name="theme-color" content="#000000">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Sean Krofssik">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta property="og:image" content="%(site)sog-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:creator" content="@SKrofssik">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="Stories by Sean Krofssik" href="%(site)sfeed.xml">
<script type="application/ld+json">%(ld)s</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
%(fonts)s
<style>%(style)s
%(extra)s</style>
</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="brand" href="/"><b>Sean Krofssik</b><span>Reporter, Hartford Courant</span></a>
    <a class="home-link" href="/#articles">All stories</a>
  </div>
</header>
<main class="wrap">
  <nav class="crumbs" aria-label="Breadcrumb"><a href="/">Sean Krofssik</a> / <span>%(nav)s</span></nav>
  <section class="box title-box">
    <h1>%(h1)s</h1>
    <p>%(intro)s</p>
  </section>
  <section class="box" aria-labelledby="list-h">
    <h2 id="list-h">%(count)d stories</h2>
    <p class="lead">Newest first. Each one links to the original story.</p>
    %(cards)s
  </section>
  <section class="box" aria-labelledby="more-h">
    <h2 id="more-h">More topics</h2>
    %(topics)s
  </section>
</main>
<footer>
  <div class="wrap row">
    <a class="brand" href="/"><b>Sean Krofssik</b><span>Reporter, Hartford Courant</span></a>
    <nav aria-label="Footer"><a href="/#articles">Articles</a><a href="/#career">Career</a><a href="/#bio">Bio</a><a href="/#contact">Contact</a></nav>
    <div>&copy; Sean Krofssik. This is my personal site, not a Hartford Courant site. Headlines link to the original stories, which belong to their publishers.</div>
  </div>
</footer>
%(beacon)s
</body>
</html>
""" % {"csp": TOPIC_CSP, "title": esc(t["title"]), "desc": esc(t["desc"]), "url": url, "site": SITE, "ld": ldtxt,
       "fonts": fonts, "style": style, "extra": extra, "nav": esc(t["nav"]), "h1": esc(t["h1"]), "intro": esc(t["intro"]),
       "count": len(stories), "cards": cards_html(stories), "topics": topics_nav(groups, current=t["slug"], label="Browse by topic"),
       "beacon": BEACON}

def replace_between(page, name, content):
    a, b = "<!-- SEO:%s:START -->" % name, "<!-- SEO:%s:END -->" % name
    i, j = page.find(a), page.find(b)
    if i < 0 or j < i:
        sys.exit("build_seo: marker %s missing in index.html" % name)
    return page[:i + len(a)] + content + page[j:]

def main():
    idx = os.path.join(ROOT, "index.html")
    page = open(idx, encoding="utf-8").read()
    stories = merge(built_in(page), from_json(os.path.join(ROOT, "stories.json")))
    if len(stories) < 10:
        sys.exit("build_seo: only %d stories found, refusing to publish a thin page" % len(stories))
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    groups = sort_topics(stories)
    src = page
    for t in TOPICS:
        if t["slug"] in groups:
            os.makedirs(os.path.join(ROOT, t["slug"]), exist_ok=True)
            with open(os.path.join(ROOT, t["slug"], "index.html"), "w", encoding="utf-8") as f:
                f.write(topic_page(t, groups[t["slug"]], groups, src, today))
    page = replace_between(page, "ARCHIVE", cards_html(stories))
    page = replace_between(page, "JSONLD", jsonld(stories, today))
    if "<!-- SEO:TOPICS:START -->" in page:
        page = replace_between(page, "TOPICS", "<style>" + TOPIC_CSS + "</style>" + topics_nav(groups))
    open(idx, "w", encoding="utf-8").write(page)
    open(os.path.join(ROOT, "feed.xml"), "w", encoding="utf-8").write(feed_xml(stories, now))
    open(os.path.join(ROOT, "llms.txt"), "w", encoding="utf-8").write(llms_txt(stories, today, groups))
    open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8").write(sitemap(today, [t["slug"] for t in TOPICS if t["slug"] in groups]))
    print("build_seo: topic pages: " + ", ".join("%s (%d)" % (k, len(v)) for k, v in groups.items()))
    direct = sum(1 for s in stories if DIRECT.match(s["u"]))
    print("build_seo: %d stories (%d direct links) written to index.html, feed.xml, llms.txt, sitemap.xml" % (len(stories), direct))
    return 0

if __name__ == "__main__":
    sys.exit(main())
