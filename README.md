# seankrofssik.com

Portfolio site for Sean Krofssik, staff reporter at the Hartford Courant.

- `site/` is the website (published with GitHub Pages).
- `site/stories.json` gets new stories automatically: `.github/workflows/site.yml` runs
  `scripts/update_stories.py` every 6 hours, which reads Sean's Courant author page and adds
  any new stories. The page loads this file and adds the stories to the Articles tabs.
- Run it by hand: Actions tab -> "Update stories and publish site" -> Run workflow.

Note: `site/index.html` has a Content-Security-Policy that only allows its inline script by
its SHA-256 hash. If you edit that script, update the hash in the CSP meta tag.
