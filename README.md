# lali-pich-site
Static replacement for the WordPress site lali-pich.com (35 pages). Built 10.10.2026 from `source/` (rendered HTML + media backup taken the same day).
- `source/html/<slug>.html`: rendered WordPress pages (input only, never served)
- `source/media/`: 91 uploaded files; `source/pages-1.json`: editor data (Elementor) for every page
- `site/<slug>/index.html`: the static page served at lali-pich.com/<slug>/ (same path as WordPress)
- `site/assets/`: CSS, JS, fonts, images referenced by the pages (relative links only: `../assets/...`)
- `tools/export.py`: turns a source page into a static page
Rules: keep the original paths, relative asset links (the site may live under a sub-path on GitHub Pages before the domain moves), no WordPress admin bar, no wp-json/REST links, no external calls to lali-pich.com.
