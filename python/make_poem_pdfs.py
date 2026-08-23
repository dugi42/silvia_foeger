"""Render the poem bands from lyrik.html into typeset PDF volumes.

The layout mirrors the website: cream paper, gold accents, Cormorant Garamond
for the verse and Raleway for the small caps. Pagination happens inside the
page (a script packs poems into fixed A5 sheets) so the table of contents can
carry real page numbers -- Chrome's print engine offers no margin boxes.

Usage:  .venv/bin/python python/make_poem_pdfs.py [band ...]
"""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "lyrik.html"
OUT_DIR = ROOT / "print"
BUILD_DIR = OUT_DIR / ".build"
FONT_DIR = BUILD_DIR / "fonts"
SPIRAL_IMG = ROOT / "assets" / "img" / "header_silvia_spiral.jpg"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

BANDS = {
    "sehnsucht": {"title": "Sehnsucht", "roman": "Band I", "file": "Sehnsucht.pdf"},
    "hoffnung": {"title": "Hoffnung", "roman": "Band II", "file": "Hoffnung.pdf"},
    "irgendwann": {"title": "Irgendwann", "roman": "Band III", "file": "Irgendwann.pdf"},
    "kindergedichte": {
        "title": "Kindergedichte",
        "roman": "Band IV",
        "file": "Kindergedichte.pdf",
    },
}

POEM_RE = re.compile(
    r'<article class="poem-leaf" data-band="(?P<band>[a-z]+)"'
    r'(?: data-group="(?P<group>[^"]+)")?>\s*'
    r'<h3 class="poem__title">(?P<title>.*?)</h3>.*?'
    r'<div class="poem__body">(?P<body>.*?)</div>\s*</article>',
    re.S,
)

# Band III is split into themed chapters by an interleaved heading.
GROUP_RE = re.compile(
    r'<h3 class="poem-group" id="[^"]*" data-band="(?P<band>[a-z]+)"'
    r' data-group="(?P<slug>[^"]+)">(?P<label>.*?)</h3>'
)

FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400"
    "&family=Raleway:wght@300;400;500;600&display=swap"
)
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
WANTED_SUBSETS = {"latin", "latin-ext"}


# ── source ────────────────────────────────────────────────────────────────

def read_band(band: str) -> list[dict]:
    """The band as chapters, in document order.

    Bands without themed headings come back as a single unlabelled chapter, so
    the layout code only has to deal with one shape.
    """
    markup = SOURCE.read_text(encoding="utf-8")
    hits = [(m.start(), "group", m) for m in GROUP_RE.finditer(markup) if m.group("band") == band]
    hits += [(m.start(), "poem", m) for m in POEM_RE.finditer(markup) if m.group("band") == band]
    hits.sort(key=lambda hit: hit[0])

    chapters: list[dict] = []
    for _, kind, match in hits:
        if kind == "group":
            chapters.append({"label": match.group("label").strip(), "poems": []})
            continue
        if not chapters:
            chapters.append({"label": None, "poems": []})
        stanzas = re.findall(r"<p>(.*?)</p>", match.group("body"), re.S)
        chapters[-1]["poems"].append(
            {
                "title": match.group("title").strip(),
                "stanzas": [re.sub(r"\s+", " ", s).strip() for s in stanzas],
            }
        )
    return [chapter for chapter in chapters if chapter["poems"]]


# ── fonts ─────────────────────────────────────────────────────────────────

def font_faces() -> str:
    """Google Fonts CSS with the latin woff2 files inlined as data URIs."""
    cached = FONT_DIR / "faces.css"
    if cached.exists():
        return cached.read_text(encoding="utf-8")

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(FONT_CSS_URL, headers={"User-Agent": CHROME_UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        css = response.read().decode("utf-8")

    faces: list[str] = []
    # Each @font-face is preceded by a /* subset */ comment.
    for subset, block in re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", css, re.S):
        if subset not in WANTED_SUBSETS:
            continue
        url_match = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not url_match:
            continue
        url = url_match.group(1)
        blob = FONT_DIR / url.rsplit("/", 1)[-1]
        if not blob.exists():
            req = urllib.request.Request(url, headers={"User-Agent": CHROME_UA})
            with urllib.request.urlopen(req, timeout=30) as response:
                blob.write_bytes(response.read())
        data = base64.b64encode(blob.read_bytes()).decode("ascii")
        faces.append(block.replace(url, f"data:font/woff2;base64,{data}"))

    if not faces:
        raise RuntimeError("no latin font faces resolved from Google Fonts")
    joined = "\n".join(faces)
    cached.write_text(joined, encoding="utf-8")
    return joined


# ── ornaments ─────────────────────────────────────────────────────────────

def golden_spiral_path(turns: float = 3.4, samples: int = 420, size: float = 100.0) -> str:
    """SVG path for a logarithmic spiral with the golden growth factor."""
    import math

    phi = (1 + 5 ** 0.5) / 2
    b = math.log(phi) / (math.pi / 2)
    theta_max = turns * 2 * math.pi
    points = []
    for i in range(samples + 1):
        theta = theta_max * i / samples
        r = math.exp(b * (theta - theta_max))
        points.append((r * math.cos(theta), r * math.sin(theta)))

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = (size * 0.94) / span
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2

    coords = [
        f"{(x - cx) * scale + size / 2:.2f} {(y - cy) * scale + size / 2:.2f}"
        for x, y in points
    ]
    return "M " + " L ".join(coords)


def spiral_svg(stroke_width: float, opacity: float = 1.0, turns: float = 3.4) -> str:
    path = golden_spiral_path(turns=turns)
    return (
        f'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" '
        f'fill="none" stroke="currentColor" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" opacity="{opacity}"><path d="{path}"/></svg>'
    )


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


# ── document ──────────────────────────────────────────────────────────────

NOISE = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'"
    "%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' "
    "numOctaves='4' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/"
    "%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='0.035'/"
    "%3E%3C/svg%3E"
)


def build_html(band: str, chapters: list[dict]) -> str:
    meta = BANDS[band]
    title = meta["title"]
    roman = meta["roman"]

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8" />
<title>Silvia Föger — {html.escape(title)} ({html.escape(roman)})</title>
<meta name="author" content="Silvia Föger" />
<style>
{font_faces()}

:root {{
  --cream: #f7f3ec;
  --parchment: #ede7db;
  --warm-white: #faf8f4;
  --ink: #1e1b18;
  --ink-soft: rgba(30, 27, 24, 0.62);
  --ink-faint: rgba(30, 27, 24, 0.4);
  --gold: #c9a455;
  --font-serif: "Cormorant Garamond", Georgia, serif;
  --font-sans: "Raleway", -apple-system, "Segoe UI", sans-serif;

  --page-w: 148mm;
  --page-h: 210mm;
  --margin-x: 17mm;
  --margin-top: 16mm;
  --margin-bottom: 15mm;
}}

@page {{ size: 148mm 210mm; margin: 0; }}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

html, body {{
  background: var(--cream);
  color: var(--ink);
  font-family: var(--font-serif);
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}

.sheet {{
  position: relative;
  width: var(--page-w);
  height: var(--page-h);
  overflow: hidden;
  background: var(--cream);
  break-after: page;
  page-break-after: always;
}}
.sheet:last-child {{ break-after: auto; page-break-after: auto; }}

/* Paper grain, as on the site hero. Cover only -- Chrome rasterises the
   turbulence filter once per sheet, which bloats the PDF by ~750 KB a page. */
.cover::before {{
  content: "";
  position: absolute;
  inset: 0;
  background-image: url("{NOISE}");
  opacity: 0.55;
  pointer-events: none;
  z-index: 1;
}}

.sheet__inner {{
  position: absolute;
  inset: var(--margin-top) var(--margin-x) var(--margin-bottom);
  display: flex;
  flex-direction: column;
}}

.sheet__content {{ flex: 1 1 auto; min-height: 0; }}
.sheet__content--center {{
  display: flex;
  flex-direction: column;
  justify-content: center;
}}

/* ── running head / foot ── */

.runhead, .runfoot {{
  font-family: var(--font-sans);
  font-size: 6.2pt;
  font-weight: 500;
  letter-spacing: 0.34em;
  text-transform: uppercase;
  color: var(--ink-faint);
  text-align: center;
  flex: 0 0 auto;
}}
.runhead {{ margin-bottom: 9mm; }}
.runfoot {{
  margin-top: 8mm;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4mm;
}}
.runfoot__rule {{
  width: 9mm;
  height: 0.4pt;
  background: linear-gradient(to right, transparent, var(--gold));
}}
.runfoot__rule--right {{ background: linear-gradient(to left, transparent, var(--gold)); }}
.runfoot__num {{
  font-family: var(--font-serif);
  font-size: 9pt;
  letter-spacing: 0.14em;
  color: var(--ink-soft);
  font-variant-numeric: lining-nums;
  font-feature-settings: "lnum" 1;
}}

/* ── cover ── */

.cover {{
  background: linear-gradient(170deg, var(--warm-white) 0%, var(--cream) 45%, var(--parchment) 100%);
}}
.cover__body {{
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 9mm;
  padding: 22mm 18mm;
  text-align: center;
  z-index: 1;
}}
.cover__author {{
  font-family: var(--font-sans);
  font-size: 7.6pt;
  font-weight: 600;
  letter-spacing: 0.46em;
  text-transform: uppercase;
  color: var(--ink-soft);
  text-indent: 0.46em;
}}
.cover__disc {{
  position: relative;
  width: 74mm;
  height: 74mm;
  border-radius: 50%;
  overflow: hidden;
  box-shadow: 0 3mm 14mm rgba(201, 164, 85, 0.34), 0 0 0 0.5pt rgba(201, 164, 85, 0.55);
}}
.cover__disc img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 51% 52%;
}}
.cover__disc::after {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, rgba(247, 243, 236, 0.16) 0%, transparent 62%);
}}
.cover__title {{
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 40pt;
  line-height: 1;
  letter-spacing: 0.12em;
  text-indent: 0.12em;
}}
.cover__rule {{ width: 18mm; height: 0.6pt; background: var(--gold); }}
.cover__band {{
  font-family: var(--font-sans);
  font-size: 7pt;
  font-weight: 500;
  letter-spacing: 0.4em;
  text-transform: uppercase;
  color: var(--ink-soft);
  text-indent: 0.4em;
}}
.cover__foot {{
  position: absolute;
  bottom: 14mm;
  left: 0;
  right: 0;
  font-family: var(--font-sans);
  font-size: 6.2pt;
  font-weight: 400;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--ink-faint);
  text-align: center;
  text-indent: 0.32em;
  z-index: 1;
}}

/* ── watermark spiral ── */

.watermark {{
  position: absolute;
  color: var(--gold);
  pointer-events: none;
  z-index: 0;
}}
.watermark svg {{ width: 100%; height: 100%; display: block; }}

/* ── title page ── */

.plate {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 6mm;
  text-align: center;
}}
.plate__author {{
  font-family: var(--font-sans);
  font-size: 7pt;
  font-weight: 600;
  letter-spacing: 0.42em;
  text-transform: uppercase;
  color: var(--ink-soft);
  text-indent: 0.42em;
}}
.plate__title {{
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 32pt;
  letter-spacing: 0.14em;
  text-indent: 0.14em;
  line-height: 1.1;
}}
.plate__rule {{ width: 14mm; height: 0.5pt; background: var(--gold); }}
.plate__band {{
  font-family: var(--font-sans);
  font-size: 6.8pt;
  font-weight: 500;
  letter-spacing: 0.38em;
  text-transform: uppercase;
  color: var(--ink-soft);
  text-indent: 0.38em;
}}
.plate__mark {{ width: 16mm; height: 16mm; color: var(--gold); margin-top: 4mm; }}
.plate__mark svg {{ width: 100%; height: 100%; }}

/* ── note page ── */

.note {{
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
  gap: 5mm;
}}
.note__label {{
  font-family: var(--font-sans);
  font-size: 6.4pt;
  font-weight: 600;
  letter-spacing: 0.38em;
  text-transform: uppercase;
  color: var(--gold);
  text-indent: 0.38em;
}}
.note__rule {{ width: 14mm; height: 0.5pt; background: var(--gold); margin-bottom: 2mm; }}
.note p {{
  font-family: var(--font-serif);
  font-size: 11.5pt;
  font-weight: 300;
  line-height: 1.72;
  color: var(--ink);
}}
.note p + p {{ margin-top: 4mm; }}
.note em {{ font-style: italic; color: var(--ink-soft); }}

/* ── contents ── */

.toc__head {{
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 20pt;
  letter-spacing: 0.2em;
  text-indent: 0.2em;
  text-align: center;
  margin-bottom: 3mm;
}}
.toc__rule {{
  width: 12mm;
  height: 0.5pt;
  background: var(--gold);
  margin: 0 auto 7mm;
}}
.toc__entry {{
  display: flex;
  align-items: baseline;
  gap: 2mm;
  font-family: var(--font-serif);
  font-size: 10pt;
  font-weight: 400;
  line-height: 1.4;
  padding: 1.15mm 0;
  color: var(--ink);
}}
.toc__entry-title {{ flex: 0 1 auto; }}
.toc__leader {{
  flex: 1 1 auto;
  border-bottom: 0.4pt dotted rgba(30, 27, 24, 0.28);
  transform: translateY(-0.9mm);
}}
.toc__group {{
  display: flex;
  align-items: baseline;
  gap: 2mm;
  font-family: var(--font-sans);
  font-size: 7pt;
  font-weight: 600;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: var(--gold);
  text-indent: 0.26em;
  padding: 3.4mm 0 1.6mm;
}}
.toc__group + .toc__entry {{ padding-top: 0; }}
.toc__group:first-child {{ padding-top: 0; }}
.toc__group .toc__leader {{ border-bottom-color: rgba(201, 164, 85, 0.45); }}
.toc__group .toc__entry-page {{
  font-family: var(--font-serif);
  font-size: 8.5pt;
  letter-spacing: 0.06em;
  color: var(--gold);
  text-transform: none;
  text-indent: 0;
}}
.toc--grouped .toc__entry {{ padding-left: 4mm; }}

.toc__entry-page {{
  flex: 0 0 auto;
  font-size: 9pt;
  letter-spacing: 0.06em;
  color: var(--ink-soft);
  font-variant-numeric: lining-nums;
  font-feature-settings: "lnum" 1;
}}

/* ── chapter opener ── */

.section-head {{
  text-align: center;
  margin-bottom: 11mm;
}}
.section-head__mark {{
  width: 9mm;
  height: 9mm;
  color: var(--gold);
  margin: 0 auto 4mm;
}}
.section-head__mark svg {{ width: 100%; height: 100%; }}
.section-head__eyebrow {{
  font-family: var(--font-sans);
  font-size: 6pt;
  font-weight: 600;
  letter-spacing: 0.38em;
  text-transform: uppercase;
  color: var(--gold);
  text-indent: 0.38em;
  margin-bottom: 3mm;
}}
.section-head__title {{
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 21pt;
  letter-spacing: 0.11em;
  text-indent: 0.11em;
  line-height: 1.2;
}}
.section-head__rule {{
  width: 12mm;
  height: 0.5pt;
  background: var(--gold);
  margin: 4mm auto 0;
}}

/* ── poems ── */

.poem {{ break-inside: avoid; }}
.poem__title {{
  font-family: var(--font-serif);
  font-weight: 400;
  font-size: 15pt;
  letter-spacing: 0.055em;
  line-height: 1.25;
  color: var(--ink);
}}
.poem__divider {{
  width: 9mm;
  height: 0.5pt;
  background: var(--gold);
  margin: 2.6mm 0 4mm;
}}
.poem__body p {{
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 11.6pt;
  line-height: 1.66;
  color: var(--ink);
  hanging-punctuation: first;
}}
.poem__body p + p {{ margin-top: 3.4mm; }}
.poem--tight .poem__title {{ font-size: 13.5pt; }}
.poem--tight .poem__body p {{ font-size: 10.4pt; line-height: 1.54; }}

.poem-sep {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3mm;
  color: var(--gold);
  margin: 8mm 0;
}}
.poem-sep__line {{ width: 15mm; height: 0.5pt; background: linear-gradient(to right, transparent, rgba(201,164,85,0.95)); }}
.poem-sep__line--right {{ background: linear-gradient(to left, transparent, rgba(201,164,85,0.95)); }}
.poem-sep__mark {{ width: 6.5mm; height: 6.5mm; }}
.poem-sep__mark svg {{ width: 100%; height: 100%; }}

/* ── colophon ── */

.colophon {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 5mm;
  text-align: center;
}}
.colophon__mark {{ width: 20mm; height: 20mm; color: var(--gold); }}
.colophon__mark svg {{ width: 100%; height: 100%; }}
.colophon__title {{
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 17pt;
  letter-spacing: 0.16em;
  text-indent: 0.16em;
}}
.colophon p {{
  font-family: var(--font-sans);
  font-size: 7.2pt;
  font-weight: 400;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  line-height: 2.1;
  color: var(--ink-soft);
  text-indent: 0.22em;
}}

#stage {{ position: absolute; visibility: hidden; left: -9999px; top: 0; }}
</style>
</head>
<body>
<div id="book"></div>
<div id="stage"></div>
<script>
const BAND = {json.dumps({"title": title, "roman": roman})};
const CHAPTERS = {json.dumps(chapters, ensure_ascii=False)};
const SPIRAL_ORNAMENT = {json.dumps(spiral_svg(2.6, turns=2.0))};
const SPIRAL_MARK = {json.dumps(spiral_svg(3.0, turns=2.1))};
const SPIRAL_WATERMARK = {json.dumps(spiral_svg(0.9, turns=3.6))};
const COVER_IMG = {json.dumps(data_uri(SPIRAL_IMG, "image/jpeg"))};
</script>
<script src="paginate.js"></script>
</body>
</html>
"""


PAGINATE_JS = r"""
/* Packs the poems into fixed A5 sheets and numbers them, so the table of
   contents can reference real pages. Chrome offers no @page margin boxes.
   Bands with themed chapters (Band III) open every chapter on a fresh sheet
   and carry the chapter name as the running head. */

const book = document.getElementById("book");
const stage = document.getElementById("stage");

const GROUPED = CHAPTERS.length > 1 || CHAPTERS.some((c) => c.label);
const TOTAL = CHAPTERS.reduce((sum, c) => sum + c.poems.length, 0);

function el(tag, cls, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

function makeSheet(cls) {
  const sheet = el("div", "sheet" + (cls ? " " + cls : ""));
  const inner = el("div", "sheet__inner");
  sheet.appendChild(inner);
  return { sheet, inner };
}

/* A numbered body sheet: running head, content well, page number. */
function makeBodySheet(pageNo, runhead) {
  const { sheet, inner } = makeSheet();
  inner.appendChild(el("div", "runhead", runhead || BAND.title));
  const content = el("div", "sheet__content");
  inner.appendChild(content);
  const foot = el("div", "runfoot");
  foot.appendChild(el("span", "runfoot__rule"));
  foot.appendChild(el("span", "runfoot__num", String(pageNo)));
  foot.appendChild(el("span", "runfoot__rule runfoot__rule--right"));
  inner.appendChild(foot);
  return { sheet, content };
}

function poemNode(poem) {
  const node = el("article", "poem");
  node.appendChild(el("h2", "poem__title", poem.title));
  node.appendChild(el("div", "poem__divider"));
  const body = el("div", "poem__body");
  poem.stanzas.forEach((s) => body.appendChild(el("p", null, s)));
  node.appendChild(body);
  return node;
}

function sectionHeadNode(label, index) {
  const head = el("header", "section-head");
  head.appendChild(el("div", "section-head__mark", SPIRAL_MARK));
  head.appendChild(el("div", "section-head__eyebrow", romanise(index) + " · Kapitel"));
  head.appendChild(el("h2", "section-head__title", label));
  head.appendChild(el("div", "section-head__rule"));
  return head;
}

function romanise(n) {
  const map = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
  let out = "";
  map.forEach(([value, sign]) => {
    while (n >= value) {
      out += sign;
      n -= value;
    }
  });
  return out;
}

function separatorNode() {
  const sep = el("div", "poem-sep");
  sep.appendChild(el("span", "poem-sep__line"));
  sep.appendChild(el("span", "poem-sep__mark", SPIRAL_ORNAMENT));
  sep.appendChild(el("span", "poem-sep__line poem-sep__line--right"));
  return sep;
}

function tocEntryNode(title, page, cls) {
  const entry = el("div", cls || "toc__entry");
  entry.appendChild(el("span", "toc__entry-title", title));
  entry.appendChild(el("span", "toc__leader"));
  entry.appendChild(el("span", "toc__entry-page", page === null ? "" : String(page)));
  return entry;
}

/* ── measure the usable well of a body sheet ── */

const probe = makeBodySheet(88, BAND.title);
stage.appendChild(probe.sheet);
const WELL_H = probe.content.clientHeight;
const WELL_W = probe.content.clientWidth;

/* Measure a node as it will render inside the well. */
const ruler = el("div", "sheet__content");
ruler.style.width = WELL_W + "px";
stage.appendChild(ruler);

function measure(node) {
  ruler.innerHTML = "";
  ruler.appendChild(node);
  const h = node.getBoundingClientRect().height;
  ruler.removeChild(node);
  return h;
}

/* Margins only resolve while the node is attached, so measure it in place. */
function measureWithMargins(node) {
  ruler.innerHTML = "";
  ruler.appendChild(node);
  const style = getComputedStyle(node);
  const h =
    node.getBoundingClientRect().height +
    parseFloat(style.marginTop) +
    parseFloat(style.marginBottom);
  ruler.removeChild(node);
  return h;
}

const SEP_H = measureWithMargins(separatorNode());

const chapters = CHAPTERS.map((chapter, i) => {
  const head = chapter.label ? sectionHeadNode(chapter.label, i + 1) : null;
  return {
    label: chapter.label,
    runhead: chapter.label || BAND.title,
    head: head,
    headHeight: head ? measureWithMargins(head) : 0,
    blocks: chapter.poems.map((poem) => {
      const node = poemNode(poem);
      let height = measure(node);
      if (height > WELL_H) {
        node.classList.add("poem--tight");
        height = measure(node);
      }
      return { poem: poem, node: node, height: height };
    }),
  };
});

/* ── pack the body ── */

const pages = [];
let current = null;
let used = 0;

function startPage(runhead) {
  current = { runhead: runhead, items: [] };
  pages.push(current);
  used = 0;
}

chapters.forEach((chapter) => {
  startPage(chapter.runhead);
  if (chapter.head) {
    current.items.push({ type: "head", node: chapter.head });
    used += chapter.headHeight;
  }
  chapter.page = pages.length - 1;
  chapter.blocks.forEach((block) => {
    const lastItem = current.items[current.items.length - 1];
    const gap = lastItem && lastItem.type === "poem" ? SEP_H : 0;
    if (current.items.length && used + gap + block.height > WELL_H) {
      startPage(chapter.runhead);
      current.items.push({ type: "poem", block: block, sep: false });
      used = block.height;
    } else {
      current.items.push({ type: "poem", block: block, sep: gap > 0 });
      used += gap + block.height;
    }
    block.page = pages.length - 1;
  });
});

/* ── contents ──
   Entry heights do not depend on the page numbers, so the contents can be
   paginated first and the numbers filled in once the offset is known. */

const tocRows = [];
chapters.forEach((chapter) => {
  if (chapter.label) {
    tocRows.push({ kind: "group", text: chapter.label, target: chapter });
  }
  chapter.blocks.forEach((block) => {
    tocRows.push({ kind: "poem", text: block.poem.title, target: block });
  });
});

const TOC_HEAD_H = (() => {
  const head = el("div");
  head.appendChild(el("h2", "toc__head", "Inhalt"));
  head.appendChild(el("div", "toc__rule"));
  return measure(head);
})();

const tocProbe = el("div", GROUPED ? "toc--grouped" : null);
ruler.innerHTML = "";
ruler.appendChild(tocProbe);
tocRows.forEach((row) => {
  const node = tocEntryNode(row.text, 88, row.kind === "group" ? "toc__group" : null);
  tocProbe.appendChild(node);
  row.height = node.getBoundingClientRect().height;
  row.node = node;
});
tocRows.forEach((row) => tocProbe.removeChild(row.node));
ruler.innerHTML = "";

const tocPages = [];
{
  let page = null;
  let space = 0;
  tocRows.forEach((row) => {
    if (!page || row.height > space) {
      page = [];
      tocPages.push(page);
      space = WELL_H - (tocPages.length === 1 ? TOC_HEAD_H : 0);
    }
    page.push(row);
    space -= row.height;
  });
}

stage.innerHTML = "";

/* 1 cover · 2 title plate · 3 note · contents · body · colophon */
const FIRST_BODY_PAGE = 3 + tocPages.length + 1;
chapters.forEach((chapter) => {
  chapter.pageNo = FIRST_BODY_PAGE + chapter.page;
  chapter.blocks.forEach((block) => {
    block.pageNo = FIRST_BODY_PAGE + block.page;
  });
});

/* ── front matter ── */

function watermark(css) {
  const mark = el("div", "watermark", SPIRAL_WATERMARK);
  Object.assign(mark.style, css);
  return mark;
}

// 1 · cover
{
  const { sheet } = makeSheet("cover");
  sheet.querySelector(".sheet__inner").remove();
  const body = el("div", "cover__body");
  body.appendChild(el("div", "cover__author", "Silvia Föger"));
  const disc = el("div", "cover__disc");
  const img = document.createElement("img");
  img.src = COVER_IMG;
  img.alt = "";
  disc.appendChild(img);
  body.appendChild(disc);
  const text = el("div");
  text.style.cssText = "display:flex;flex-direction:column;align-items:center;gap:5mm;";
  text.appendChild(el("h1", "cover__title", BAND.title));
  text.appendChild(el("div", "cover__rule"));
  text.appendChild(el("div", "cover__band", BAND.roman + " · Gedichte"));
  body.appendChild(text);
  sheet.appendChild(body);
  sheet.appendChild(el("div", "cover__foot", "Lyrik aus dem Wortarchiv"));
  book.appendChild(sheet);
}

// 2 · title plate
{
  const { sheet, inner } = makeSheet();
  const plate = el("div", "plate");
  plate.appendChild(el("div", "plate__author", "Silvia Föger"));
  plate.appendChild(el("h1", "plate__title", BAND.title));
  plate.appendChild(el("div", "plate__rule"));
  plate.appendChild(el("div", "plate__band", BAND.roman + " · Gedichte"));
  plate.appendChild(el("div", "plate__mark", SPIRAL_MARK));
  inner.appendChild(plate);
  inner.style.zIndex = "1";
  book.appendChild(sheet);
}

// 3 · note
{
  const { sheet, inner } = makeSheet();
  sheet.appendChild(
    watermark({
      width: "150mm",
      height: "150mm",
      left: "-62mm",
      top: "-34mm",
      opacity: "0.07",
    })
  );
  const note = el("div", "note");
  note.appendChild(el("div", "note__label", "Zu diesem Band"));
  note.appendChild(el("div", "note__rule"));
  note.appendChild(
    el(
      "p",
      null,
      "Dieser Band versammelt " +
        TOTAL +
        " Gedichte von Silvia Föger — " +
        BAND.roman +
        " ihres Wortarchivs, hier unter dem Titel <em>" +
        BAND.title +
        "</em>" +
        (GROUPED ? ", geordnet in " + chapters.length + " Kapiteln" : "") +
        "."
    )
  );
  note.appendChild(
    el(
      "p",
      null,
      "Die Spirale steht für Anfang und Ende, für Wandel und Heimkommen, für die Wege des Lebens, die sich winden und doch immer weiterführen. Sie begleitet diese Verse wie die Arbeiten aus Ton."
    )
  );
  inner.appendChild(note);
  inner.style.zIndex = "1";
  book.appendChild(sheet);
}

// contents
tocPages.forEach((rows, i) => {
  const { sheet, content } = makeBodySheet(4 + i, "Inhalt");
  if (i === 0) {
    content.appendChild(el("h2", "toc__head", "Inhalt"));
    content.appendChild(el("div", "toc__rule"));
  }
  const list = el("div", GROUPED ? "toc--grouped" : null);
  rows.forEach((row) => {
    list.appendChild(
      tocEntryNode(row.text, row.target.pageNo, row.kind === "group" ? "toc__group" : null)
    );
  });
  content.appendChild(list);
  book.appendChild(sheet);
});

// body
pages.forEach((page, i) => {
  const { sheet, content } = makeBodySheet(FIRST_BODY_PAGE + i, page.runhead);
  // A lone short poem is centred rather than stranded under the running head.
  const only = page.items.length === 1 ? page.items[0] : null;
  if (only && only.type === "poem" && only.block.height < WELL_H * 0.68) {
    content.classList.add("sheet__content--center");
  }
  page.items.forEach((item) => {
    if (item.type === "head") {
      content.appendChild(item.node);
      return;
    }
    if (item.sep) content.appendChild(separatorNode());
    content.appendChild(item.block.node);
  });
  book.appendChild(sheet);
});

// colophon
{
  const { sheet, inner } = makeSheet();
  sheet.appendChild(
    watermark({
      width: "138mm",
      height: "138mm",
      left: "50%",
      top: "50%",
      transform: "translate(-50%, -50%)",
      opacity: "0.06",
    })
  );
  const colo = el("div", "colophon");
  colo.appendChild(el("div", "colophon__mark", SPIRAL_MARK));
  colo.appendChild(el("div", "colophon__title", BAND.title));
  colo.appendChild(
    el(
      "p",
      null,
      "Silvia Föger<br />Keramik · Lyrik · Gestalttherapeutische Projekte<br />Thaur, Tirol, Österreich"
    )
  );
  colo.appendChild(el("p", null, "© Silvia Föger · Alle Rechte vorbehalten"));
  inner.appendChild(colo);
  inner.style.zIndex = "1";
  book.appendChild(sheet);
}

window.__sheetCount = book.children.length;
"""


# ── rendering ─────────────────────────────────────────────────────────────

def render(band: str) -> Path:
    meta = BANDS[band]
    chapters = read_band(band)
    if not chapters:
        raise RuntimeError(f"no poems found for band {band!r}")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "paginate.js").write_text(PAGINATE_JS, encoding="utf-8")
    html_path = BUILD_DIR / f"{band}.html"
    html_path.write_text(build_html(band, chapters), encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUT_DIR / meta["file"]
    subprocess.run(
        [
            CHROME,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--allow-file-access-from-files",
            "--virtual-time-budget=30000",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    total = sum(len(chapter["poems"]) for chapter in chapters)
    chaptered = f", {len(chapters)} Kapitel" if len(chapters) > 1 else ""
    print(f"{meta['file']}: {total} Gedichte{chaptered}")
    return pdf_path


def main() -> int:
    if not Path(CHROME).exists():
        print("Google Chrome not found", file=sys.stderr)
        return 1
    bands = sys.argv[1:] or list(BANDS)
    for band in bands:
        if band not in BANDS:
            print(f"unknown band: {band}", file=sys.stderr)
            return 1
        render(band)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
