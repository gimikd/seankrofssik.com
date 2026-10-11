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

def llms_txt(stories, today):
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
        "## Stories (newest first, updated %s)" % today,
    ]
    for s in stories:
        lines.append("- [%s](%s): %s, %s, %s" % (s["t"].replace("[", "(").replace("]", ")"), s["u"], outlet(s),
                                                 SECTIONS.get(s.get("s"), "Community"), nice_date(s["d"])))
    return "\n".join(lines) + "\n"

def sitemap(today):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "  <url><loc>%s</loc><lastmod>%s</lastmod><changefreq>daily</changefreq></url>\n</urlset>\n" % (SITE, today))

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
    page = replace_between(page, "ARCHIVE", cards_html(stories))
    page = replace_between(page, "JSONLD", jsonld(stories, today))
    open(idx, "w", encoding="utf-8").write(page)
    open(os.path.join(ROOT, "feed.xml"), "w", encoding="utf-8").write(feed_xml(stories, now))
    open(os.path.join(ROOT, "llms.txt"), "w", encoding="utf-8").write(llms_txt(stories, today))
    open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8").write(sitemap(today))
    direct = sum(1 for s in stories if DIRECT.match(s["u"]))
    print("build_seo: %d stories (%d direct links) written to index.html, feed.xml, llms.txt, sitemap.xml" % (len(stories), direct))
    return 0

if __name__ == "__main__":
    sys.exit(main())
