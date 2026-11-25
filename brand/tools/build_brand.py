# /// script
# requires-python = ">=3.10"
# dependencies = ["fonttools>=4.50", "uharfbuzz>=0.40", "brotli", "cairosvg>=2.7"]
# ///
"""Build the RunPapers brand files from brand/color/palette.json and the fonts in brand/fonts/.

    uv run brand/tools/build_brand.py

Writes: logo/*.svg (text as outlines, so they open the same everywhere), icons/*.svg|png, social/og-card.svg|png,
color/tokens.css and color/runpapers.ase (Adobe swatches), fonts/SourceSerif4-Variable-latin.woff2.
The SVGs are plain shapes with named ids: once you edit one in Illustrator, that file is the source; rerunning this
script overwrites it, so keep your edited copies (or change the numbers here).
"""
import io
import json
import os
import struct
import sys

import uharfbuzz as hb
from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # brand/
FONTS = os.path.join(HERE, "fonts")
SANS = os.path.join(FONTS, "IBMPlexSans-Variable.ttf")        # interface, headings, the name
SERIF = os.path.join(FONTS, "SourceSerif4-Variable.ttf")      # paper titles

P = {c["id"]: c["hex"] for c in json.load(open(os.path.join(HERE, "color", "palette.json")))["colors"]}
INK, EOSIN, EOSIN_BRIGHT, SLIDE, COVERSLIP, MUTED, WHITE = (
    P["hematoxylin"], P["eosin"], P["eosin-bright"], P["slide"], P["coverslip"], P["counterstain"], "#FFFFFF")

_cache = {}


def _instance(path, **axes):
    key = (path, tuple(sorted(axes.items())))
    if key not in _cache:
        f = TTFont(path)
        inst = instancer.instantiateVariableFont(f, axes) if "fvar" in f else f
        buf = io.BytesIO()
        inst.save(buf)
        data = buf.getvalue()
        _cache[key] = (TTFont(io.BytesIO(data)), data)
    return _cache[key]


def text_path(text, size, x, y, path=SANS, tracking=0.0, **axes):
    """Outline `text` (kerned by HarfBuzz) with its baseline at (x, y). Returns (svg path d, width, cap height)."""
    font, data = _instance(path, **axes)
    upem = font["head"].unitsPerEm
    hbfont = hb.Font(hb.Face(data))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf, {"kern": True, "liga": True})
    gs = font.getGlyphSet()
    s = size / upem
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    px = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        name = font.getGlyphName(info.codepoint)
        gs[name].draw(TransformPen(pen, (s, 0, 0, -s, x + (px + pos.x_offset) * s, y - pos.y_offset * s)))
        px += pos.x_advance + tracking * upem
    cap = getattr(font["OS/2"], "sCapHeight", 0) or upem * 0.7
    return pen.getCommands(), (px - tracking * upem) * s, cap * s


def svg(w, h, body, title="RunPapers"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}">\n'
            f'  <title>{title}</title>\n{body}\n</svg>\n')


def mark(axes=INK, run=EOSIN, dx=0, dy=0, scale=1.0):
    """The mark: a figure's axes with a run (play) triangle in the plot area. 64 x 64 units."""
    t = f' transform="translate({dx:g} {dy:g}) scale({scale:g})"' if (dx or dy or scale != 1) else ""
    return (f'  <g id="mark"{t}>\n'
            f'    <path id="axes" d="M12 12V52H52" fill="none" stroke="{axes}" stroke-width="7" '
            f'stroke-linecap="round" stroke-linejoin="round"/>\n'
            f'    <path id="run" d="M24 18V42L44 30Z" fill="{run}" stroke="{run}" stroke-width="5" stroke-linejoin="round"/>\n'
            f'  </g>')


def wordmark(color, x, baseline, cap_target=32.0, serif=False):
    font = dict(path=SERIF, wght=700, opsz=60) if serif else dict(path=SANS, wght=700)
    d, w, cap = text_path("RunPapers", 100, 0, 0, **font)
    size = 100 * cap_target / cap
    d, w, _ = text_path("RunPapers", size, x, baseline, **font)
    return f'  <path id="wordmark" fill="{color}" d="{d}"/>', w


def lockup(axes, run, text, name, serif=False):
    # mark 0..64; caps 32 units tall, centred on the mark (baseline 48)
    wm, w = wordmark(text, 76, 48, serif=serif)
    width = 76 + w + 4
    out = svg(round(width, 1), 64, mark(axes, run) + "\n" + wm, "RunPapers")
    open(os.path.join(HERE, "logo", name), "w").write(out)
    return width


def write(rel, text):
    p = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)


def png(rel_svg, rel_png, width):
    import cairosvg
    cairosvg.svg2png(url=os.path.join(HERE, rel_svg), write_to=os.path.join(HERE, rel_png), output_width=width)


def ase(colors, path):
    """Adobe Swatch Exchange (Illustrator: Swatches panel menu -> Open Swatch Library -> Other Library)."""
    blocks = b""
    for c in colors:
        name = (c["name"] + "\0").encode("utf-16-be")
        r, g, b = (int(c["hex"][i:i + 2], 16) / 255 for i in (1, 3, 5))
        body = struct.pack(">H", len(name) // 2) + name + b"RGB " + struct.pack(">fffH", r, g, b, 0)
        blocks += struct.pack(">HI", 1, len(body)) + body
    open(path, "wb").write(b"ASEF" + struct.pack(">HHI", 1, 0, len(colors)) + blocks)


def woff2(src, out, **axes_keep):
    f = TTFont(src)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    # Latin, Latin-1, Latin Extended-A, Greek (gene and statistics symbols), punctuation, arrows, maths
    uni = list(range(0x20, 0x7F)) + list(range(0xA0, 0x180)) + list(range(0x370, 0x400)) + \
        list(range(0x2000, 0x2070)) + [0x2190, 0x2192, 0x2212, 0x2264, 0x2265, 0x00D7, 0x2248, 0x2206, 0x221E, 0x2713]
    sub.populate(unicodes=uni)
    sub.subset(f)
    f.flavor = "woff2"
    f.save(os.path.join(FONTS, out))


def main():
    # logos
    lockup(INK, EOSIN, INK, "runpapers-logo.svg")
    lockup(WHITE, EOSIN_BRIGHT, WHITE, "runpapers-logo-reverse.svg")
    lockup(INK, INK, INK, "runpapers-logo-ink.svg")
    lockup("#000000", "#000000", "#000000", "runpapers-logo-black.svg")
    lockup(WHITE, WHITE, WHITE, "runpapers-logo-white.svg")
    lockup(INK, EOSIN, INK, "runpapers-logo-serif.svg", serif=True)   # alternate: the name in Source Serif 4
    write("logo/runpapers-mark.svg", svg(64, 64, mark()))
    write("logo/runpapers-mark-reverse.svg", svg(64, 64, mark(WHITE, EOSIN_BRIGHT)))
    write("logo/runpapers-mark-black.svg", svg(64, 64, mark("#000000", "#000000")))
    write("logo/runpapers-mark-white.svg", svg(64, 64, mark(WHITE, WHITE)))
    wm, w = wordmark(INK, 2, 40)
    write("logo/runpapers-wordmark.svg", svg(round(w + 4, 1), 48, wm))
    # live text (edit the words in Illustrator; install the fonts in brand/fonts first)
    _, w, cap = text_path("RunPapers", 100, 0, 0, wght=700)
    size = 100 * 32 / cap
    write("logo/runpapers-logo-editable-text.svg", svg(round(76 + w * size / 100 + 4, 1), 64, mark() + "\n" +
          f'  <text id="wordmark" x="76" y="48" font-family="IBM Plex Sans" font-weight="700" '
          f'font-size="{size:.2f}" fill="{INK}">RunPapers</text>'))

    # icons: a filled tile reads better at 16-32 px
    tile = (f'  <rect id="tile" width="64" height="64" rx="14" fill="{INK}"/>\n' +
            mark(WHITE, EOSIN_BRIGHT, dx=4.8, dy=4.8, scale=0.85))
    write("icons/favicon.svg", svg(64, 64, tile))
    write("icons/icon-maskable.svg", svg(64, 64, f'  <rect width="64" height="64" fill="{INK}"/>\n' +
                                         mark(WHITE, EOSIN_BRIGHT, dx=12.8, dy=12.8, scale=0.6)))
    for size, name in ((32, "favicon-32.png"), (180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        png("icons/favicon.svg", f"icons/{name}", size)
    png("icons/icon-maskable.svg", "icons/icon-maskable-512.png", 512)

    # social card 1200 x 630
    wm, w = wordmark(INK, 0, 0)
    l1, _, _ = text_path("Reproduce the paper.", 70, 80, 300, wght=700)
    l2, _, _ = text_path("Then ask your own question.", 70, 80, 384, wght=700)
    sub1, _, _ = text_path("Ready-made packs for published papers. Your own AI agent reproduces", 30, 80, 470, wght=400)
    sub2, _, _ = text_path("the figures from the original data, then answers your questions.", 30, 80, 512, wght=400)
    url, _, _ = text_path("runpapers.com", 28, 80, 566, wght=600)
    card = (f'  <rect width="1200" height="630" fill="{SLIDE}"/>\n'
            f'  <g id="logo" transform="translate(80 72) scale(0.875)">\n{mark()}\n'
            f'  <g transform="translate(76 48)">{wm.strip()}</g>\n  </g>\n'
            f'  <path id="tagline" fill="{INK}" d="{l1} {l2}"/>\n'
            f'  <path id="subline" fill="{MUTED}" d="{sub1} {sub2}"/>\n'
            f'  <path id="url" fill="{P["eosin-ink"]}" d="{url}"/>\n'
            f'  <rect id="band" x="0" y="618" width="1200" height="12" fill="{EOSIN}"/>')
    write("social/og-card.svg", svg(1200, 630, card, "RunPapers: reproduce the paper, then ask your own question"))
    png("social/og-card.svg", "social/og-card.png", 1200)

    # colour files
    pal = json.load(open(os.path.join(HERE, "color", "palette.json")))
    ase(pal["colors"], os.path.join(HERE, "color", "runpapers.ase"))
    css = ["/* RunPapers colour and type tokens. Generated from brand/color/palette.json by brand/tools/build_brand.py */",
           ":root {"]
    css += [f"  --rp-{c['id']}: {c['hex']};  /* {c['name']}: {c['use']} */" for c in pal["colors"]]
    css += ['  --rp-font-sans: "IBM Plex Sans", -apple-system, "Segoe UI", Roboto, sans-serif;',
            '  --rp-font-serif: "Source Serif 4", Georgia, serif;',
            '  --rp-font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;   /* commands only */', "}"]
    css += ["@media (prefers-color-scheme: dark) {", "  :root {"]
    css += [f"    --rp-{k}: {v};" for k, v in pal["dark"].items()]
    css += ["  }", "}"]
    write("color/tokens.css", "\n".join(css) + "\n")

    # web fonts. IBM Plex Sans: IBM's own split woff2 files are used as they are (its licence reserves the name
    # "Plex" for unmodified fonts, so we don't subset it). Source Serif 4 has no reserved name: subset to Latin.
    woff2(SERIF, "SourceSerif4-Variable-latin.woff2")
    print("brand files written to", HERE)


if __name__ == "__main__":
    sys.exit(main())
