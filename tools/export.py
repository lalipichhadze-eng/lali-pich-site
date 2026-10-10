#!/usr/bin/env python3
"""Static export of rendered WordPress/Elementor pages.

  python tools/export.py <slug> [<slug> ...]   source/html/<slug>.html -> site/<slug>/index.html (+ site/assets/)
  python tools/export.py --all                 every page in source/html
  python tools/export.py --check               no lali-pich.com / wp-content / wp-includes URL left in site/, all ../assets refs exist

Assets (CSS/JS/fonts/images, url() and @import inside CSS recursively, any host for stylesheets) are downloaded once
into site/assets/<stem>-<hash8><ext> (hash of the URL without ?ver, so names are stable and parallel-lane safe).
Raw downloads are cached in tools/.cache (gitignored), so re-runs are offline-fast.
Elementor Pro JS is dropped (needs the Pro licence server); forms and countdown get a plain replacement (see forms.js).
"""
import hashlib, json, mimetypes, os, re, sys
import urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, SITE = os.path.join(ROOT, "source", "html"), os.path.join(ROOT, "site")
ASSETS, CACHE = os.path.join(SITE, "assets"), os.path.join(ROOT, "tools", ".cache")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
OWN = r"(?:www\.)?lali-pich\.com"
EL_BASE = "/wp-content/plugins/elementor/assets/"
EL_EXTRA = ["lib/dialog/dialog.min.js", "lib/swiper/v8/swiper.min.js", "lib/swiper/v8/css/swiper.min.css",
            "lib/share-link/share-link.min.js", "css/conditionals/lightbox.min.css", "css/conditionals/dialog.min.css"]
# where a form's submit sends the visitor (data-redirect on the <form>); forms.js has the CRM endpoint constant
CALENDLY = "https://calendly.com/lalipichhadze/naturallove"
GROW = "https://pay.grow.link/f87954497ef16c5f8c7327cafe1e3a41-MjE4NjE4Mw"
REDIRECT = {"toxic-relationship-analyze": CALENDLY}
REDIRECT_DEFAULT = GROW  # ponytail: every other page's form goes to Grow until a lane says otherwise


def fetch(url):
    """(bytes, content-type) with disk cache + retries."""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(cp):
        return open(cp, "rb").read(), open(cp + ".t").read()
    u = urllib.parse.urlsplit(url)
    safe = urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(u.path, safe="/%:@!$&'()*+,;=~-._"),
                                    urllib.parse.quote(u.query, safe="=&%:/,;+@~-._"), ""))
    err = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(safe, headers={"User-Agent": UA}), timeout=40) as r:
                data, ct = r.read(), r.headers.get("Content-Type", "")
            open(cp, "wb").write(data); open(cp + ".t", "w").write(ct)
            return data, ct
        except Exception as e:  # noqa
            err = e
    raise RuntimeError(f"{url}: {err}")


class Assets:
    def __init__(self):
        self.got, self.failed, self.want = {}, {}, set()

    def key(self, url):
        u = urllib.parse.urlsplit(url)
        if re.fullmatch(OWN, u.netloc):
            return u.netloc.replace("www.", "") + u.path
        return urllib.parse.urlunsplit(u._replace(fragment=""))

    def name(self, url):
        _, ct = self.got[url]
        p = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
        stem, ext = os.path.splitext(os.path.basename(p))
        ext = ext.lower() if re.fullmatch(r"\.[a-z0-9]{1,6}", ext.lower()) else (mimetypes.guess_extension(ct.split(";")[0].strip()) or "")
        if ext == ".jpe": ext = ".jpg"
        if "css" in ct and ext != ".css": ext = ".css"
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:40] or "f"
        return f"{stem}-{hashlib.sha1(self.key(url).encode()).hexdigest()[:8]}{ext}"

    def is_css(self, url):
        return self.name(url).endswith(".css")

    def resolve(self):
        """BFS: fetch everything wanted, parse CSS for more."""
        todo = set(self.want)
        while todo:
            todo = {u for u in todo if u not in self.got and u not in self.failed}
            with ThreadPoolExecutor(16) as ex:
                res = list(ex.map(lambda u: (u, self._try(u)), todo))
            todo = set()
            for u, r in res:
                if r is None: continue
                self.got[u] = r
                if self.is_css(u):
                    for ref in css_refs(r[0].decode("utf-8", "replace"), u):
                        todo.add(ref)

    def _try(self, u):
        try:
            return fetch(u)
        except Exception as e:  # noqa
            self.failed[u] = str(e)
            print("FAIL", e, file=sys.stderr)

    def write(self):
        os.makedirs(ASSETS, exist_ok=True)
        for u, (data, _) in self.got.items():
            n = self.name(u)
            if n.endswith(".css"):
                data = rewrite_css(data.decode("utf-8", "replace"), u, self).encode("utf-8")
            open(os.path.join(ASSETS, n), "wb").write(data)


CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)|@import\s+(['"])(.*?)\3""", re.S)


def _cssref(m):
    return m.group(2) if m.group(2) is not None else m.group(4)


def css_refs(text, base):
    out = []
    for m in CSS_URL.finditer(text):
        r = (_cssref(m) or "").strip()
        if r and not r.startswith(("data:", "#", "about:")):
            out.append(urllib.parse.urldefrag(urllib.parse.urljoin(base, r.replace("&amp;", "&")))[0])
    return out


def rewrite_css(text, base, A):
    def sub(m):
        r = (_cssref(m) or "").strip()
        if not r or r.startswith(("data:", "#", "about:")): return m.group(0)
        full = urllib.parse.urljoin(base, r)
        u, frag = urllib.parse.urldefrag(full)
        if u not in A.got: return m.group(0)
        n = A.name(u) + ("#" + frag if frag else "")
        return f"url({n})" if m.group(2) is not None else f'@import "{n}"'
    return CSS_URL.sub(sub, text)


# ---------- HTML ----------
LINK_JUNK = re.compile(r"""<link\b[^>]*\brel=(["'])(?:alternate|https://api\.w\.org/|EditURI|shortlink|canonical|wlwmanifest|pingback|dns-prefetch)\1[^>]*>\s*""", re.I)
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>\s*", re.S | re.I)
STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
SELF = re.compile(r"(?:https?:)?(\\?/)\1" + OWN + r"((?:\\?/[^\s\"'<>()\\&,;{}#]*)*)(#[^\s\"'<>()\\&]*)?", re.I)
SHEET = re.compile(r"""(<link\b[^>]*\brel=['"]stylesheet['"][^>]*\bhref=)(['"])(.*?)\2""", re.I)


def drop_balanced_div(h, start_re):
    m = re.search(start_re, h)
    if not m: return h
    depth, i = 0, m.start()
    for t in re.finditer(r"<(/?)div\b", h[i:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return h[:i] + h[h.find(">", i + t.end()) + 1:]
    return h


def clean(h):
    h = drop_balanced_div(h, r"<div[^>]*\bid=['\"]wpadminbar['\"]")
    h = re.sub(r"<(?:link|style)\b[^>]*\bid=['\"][^'\"]*admin-bar[^'\"]*['\"].*?(?:/>|>|</style>)", "", h, flags=re.S) if "admin-bar" in h else h
    h = re.sub(r"(<body\b[^>]*\bclass=['\"][^'\"]*)\b(?:admin-bar|customize-support)\b\s*", r"\1", h)
    h = LINK_JUNK.sub("", h)
    h = re.sub(r"<meta\s+(?:name=['\"]generator['\"]|property=['\"]og:url['\"])[^>]*>\s*", "", h, flags=re.I)

    def script(m):
        s = m.group(0)
        bad = ("elementor-pro" in s or "ElementorProFrontendConfig" in s or "wp-emoji" in s or "_wpemojiSettings" in s
               or "speculationrules" in s[:200])
        return "" if bad else s
    h = SCRIPT.sub(script, h)
    # comments, outside script/style
    parts = re.split(r"(<script\b.*?</script>|<style\b.*?</style>)", h, flags=re.S | re.I)
    return "".join(p if i % 2 else re.sub(r"<!--.*?-->", "", p, flags=re.S) for i, p in enumerate(parts))


def forms_and_countdown(h, slug):
    n = 0

    def form(m):
        nonlocal n
        n += 1
        red = REDIRECT.get(slug, REDIRECT_DEFAULT)
        return f'<form class="elementor-form lp-form" method="post" data-redirect="{red}">'
    h = re.sub(r"<form\b[^>]*class=\"elementor-form\"[^>]*>", form, h)
    h = re.sub(r"\s*<input type=\"hidden\" name=\"(?:post_id|form_id|referer_title|queried_id)\"[^>]*>", "", h)
    h = re.sub(r"(elementor-widget-form\" data-id=\"\w+\" data-element_type=\"widget\" data-e-type=\"widget\") data-settings=\"[^\"]*\" data-widget_type=\"form\.default\"", r"\1", h)

    def cd(m):
        s = int(m.group(1)); d = {"hours": s // 3600, "minutes": s % 3600 // 60, "seconds": s % 60}
        body = re.sub(r"(elementor-countdown-(hours|minutes|seconds)\">)</span>", lambda k: f"{k.group(1)}{d[k.group(2)]:02d}</span>", m.group(3))
        return f'<div class="elementor-countdown-wrapper">{body}</div>'
    h = re.sub(r"<div data-evergreen-interval=\"(\d+)\" class=\"elementor-countdown-wrapper\" data-date=\"([^\"]*)\">(.*?)</div>\s*</div>",
               lambda m: cd(m) + "\n</div>", h, flags=re.S)
    if n and "forms.js" not in h:
        h = h.replace("</body>", '<script src="../assets/forms.js" defer></script>\n</body>', 1)
    return h


class Pass:
    """One rewriting pass over HTML text; collect mode (A.want) or rewrite mode."""
    def __init__(self, A, slugs, collect):
        self.A, self.slugs, self.collect, self.el = A, slugs, collect, False
        self.missing = set()

    def self_url(self, m):
        esc = "\\" if m.group(1).startswith("\\") else ""
        path, frag = urllib.parse.unquote(m.group(2).replace("\\/", "/")), m.group(3) or ""
        url = "https://lali-pich.com" + m.group(2).replace("\\/", "/")
        def out(s): return s.replace("/", "\\/") if esc else s
        if path == EL_BASE:
            self.el = True
            return out("../assets/el/")
        if path.rstrip("/") == "/wp-content/uploads": return out("../assets")
        if re.match(r"/(wp-admin|wp-json|xmlrpc|feed|comments|wp-login)", path) or m.group(2) in ("", "/") and "?" in frag:
            return ""
        if path.startswith(("/wp-content/", "/wp-includes/")) or re.search(r"\.[A-Za-z0-9]{2,5}$", path):
            url = url.split("?")[0]
            if self.collect:
                self.A.want.add(url); return m.group(0)
            return out("../assets/" + self.A.name(url)) if url in self.A.got else m.group(0)
        slug = path.strip("/")
        if slug and slug not in self.slugs: self.missing.add(slug)
        return out("../" + (slug + "/" if slug else "") + frag)

    def sheet(self, m):
        href = m.group(3).replace("&amp;", "&").replace("&#038;", "&")
        if re.match(r"(?:https?:)?//" + OWN, href): return m.group(0)
        if href.startswith("//"): href = "https:" + href
        if not href.startswith("http"): return m.group(0)
        if self.collect:
            self.A.want.add(href); return m.group(0)
        return f"{m.group(1)}{m.group(2)}../assets/{self.A.name(href)}{m.group(2)}" if href in self.A.got else m.group(0)

    def run(self, h):
        h = SHEET.sub(self.sheet, h)
        return SELF.sub(self.self_url, h)


def elementor_extras(A, h):
    """Elementor lazy-loads handler chunks + libs from urls.assets; mirror them to site/assets/el/."""
    wr = next((d for u, (d, _) in A.got.items() if "webpack.runtime" in u and "pro" not in u), b"").decode("utf-8", "replace")
    files = ["js/" + n for n in set(re.findall(r'"([\w.-]+\.bundle\.min\.js)"', wr))] + EL_EXTRA
    base = "https://lali-pich.com" + EL_BASE
    def one(f):
        try:
            d, _ = fetch(base + f)
            p = os.path.join(ASSETS, "el", f); os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(d)
        except Exception as e:  # noqa
            print("FAIL", e, file=sys.stderr)
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(one, files))


def export(slugs_to_do, all_slugs):
    pages = {}
    for s in slugs_to_do:
        h = open(os.path.join(SRC, s + ".html"), encoding="utf-8", newline="").read()
        pages[s] = forms_and_countdown(clean(h), s)
    A = Assets()
    for s, h in pages.items():
        p = Pass(A, all_slugs, True); p.run(h)
    A.resolve(); A.write()
    el = False
    for s, h in pages.items():
        p = Pass(A, all_slugs, False)
        out = p.run(h); el |= p.el
        os.makedirs(os.path.join(SITE, s), exist_ok=True)
        open(os.path.join(SITE, s, "index.html"), "w", encoding="utf-8", newline="").write(out)
        print(f"{s}: {len(out)//1024} KB" + (f", links to unexported/unknown pages: {sorted(p.missing)}" if p.missing else ""))
    if el: elementor_extras(A, "")
    print(f"assets: {len(A.got)} files, failed: {len(A.failed)}")
    return 1 if A.failed else 0


def check():
    bad = re.compile(r"(?:https?:)?(?:\\?/){2}" + OWN + r"|wp-(?:content|includes)(?:\\?/)", re.I)
    ref = re.compile(r"""(?:src|href|poster)=["']\.\./assets/([^"'#?]+)""")
    n, probs = 0, []
    for d, _, fs in os.walk(SITE):
        for f in fs:
            if not f.endswith((".html", ".css", ".js", ".json", ".svg")): continue
            p = os.path.join(d, f); t = open(p, encoding="utf-8", errors="replace").read(); n += 1
            for m in bad.finditer(t):
                probs.append(f"{os.path.relpath(p, SITE)}: {t[max(0, m.start()-30):m.end()+40]!r}")
            if f.endswith(".html"):
                probs += [f"{os.path.relpath(p, SITE)}: missing asset {a}" for a in ref.findall(t) if not os.path.exists(os.path.join(ASSETS, a))]
    print(f"checked {n} files, {len(probs)} problems")
    for x in probs[:40]: print(" ", x)
    return 1 if probs else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--check"]: sys.exit(check())
    allp = sorted(f[:-5] for f in os.listdir(SRC) if f.endswith(".html"))
    do = allp if a == ["--all"] else a
    if not do or any(x.startswith("-") for x in do): sys.exit(__doc__)
    sys.exit(export(do, set(allp)))
