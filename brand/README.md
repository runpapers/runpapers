# RunPapers brand kit

Everything that makes RunPapers look and sound like itself. Open `preview.html` in a browser to see it all on one
page.

## The idea
Two things from a biologist's bench. **The mark** is a figure's axes with a run triangle in the plot area: a
figure that runs. **The colours** are the H&E stain on a glass slide: hematoxylin (blue-violet ink) for text and
structure, eosin (pink) for the one thing that moves. **The type** is Atkinson Hyperlegible, designed by the
Braille Institute so that look-alike characters stay distinct: I, l and 1 in gene names (Il1b, SLC17A7) and O
and 0 in DOIs never get confused. Paper titles and quotes from papers are set in Newsreader, a reading serif:
the paper's voice in serif, ours in Atkinson.

## Folders
| Folder | What | Edit in |
|---|---|---|
| `logo/` | `runpapers-logo.svg` (mark + name, colour), `-reverse` (on dark), `-ink` and `-black` (one colour), `-white`; `runpapers-mark*.svg` (the mark alone); `runpapers-wordmark.svg`; `runpapers-logo-editable-text.svg` (the name as live text) | Illustrator, Inkscape, Figma |
| `icons/` | `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png` (180), `icon-192/512.png`, `icon-maskable` | Illustrator |
| `social/` | `og-card.svg` / `.png` (1200 x 630, the preview image when a link is shared) | Illustrator |
| `color/` | `palette.json` (the source), `tokens.css` (for the website), `runpapers.ase` (Adobe swatches) | any text editor; Illustrator |
| `fonts/` | the three font families (variable TTF for your computer, Latin `.woff2` for the website) and their licences (SIL Open Font License: free to use, embed and modify) | - |
| `copy.md` | tagline, descriptions, page texts, search-result layout, profile bios, voice rules | any text editor |
| `tools/build_brand.py` | rebuilds the files above from `palette.json` and the fonts | - |

## Editing in Illustrator
- **Open any SVG** with File > Open. Shapes are named: `axes`, `run`, `wordmark`, `tile`, `tagline`.
- The name in `runpapers-logo.svg` is already **outlined** (shapes, not text), so it looks the same on every
  computer. To change the letters, install the fonts first (double-click the `.ttf` files in `fonts/`), then open
  `runpapers-logo-editable-text.svg`, edit, and Type > Create Outlines before saving.
- The mark's lines are strokes (7 units for the axes, round ends). If you scale the mark, keep
  Preferences > General > "Scale Strokes & Effects" on, or use Object > Expand to turn them into shapes.
- **Swatches**: Swatches panel menu > Open Swatch Library > Other Library > `color/runpapers.ase`.
- Save back as SVG (File > Save As > SVG, "Presentation attributes", fonts "Convert to outline"). Once you have
  edited a file by hand, keep your version: rerunning `tools/build_brand.py` overwrites these files.

## Colours
| Name | Hex | Use |
|---|---|---|
| Hematoxylin | `#2A2C6B` | text, headings, the mark's axes (12.6:1 on white) |
| Eosin | `#D9466F` | the run triangle and large accents only, never small text |
| Eosin ink | `#C2335E` | links and buttons (white text on it 5.3:1) |
| Eosin bright | `#FF6B93` | the run triangle on dark backgrounds |
| Eosin wash | `#FCEEF2` | the copy-prompt panel, highlights |
| Slide | `#F7F7FB` | page background |
| Coverslip | `#E3E2EE` | lines, borders, table rules |
| Counterstain | `#5D5A85` | secondary text: authors, dates, counts |

Dark-mode values are in `palette.json`. Every text colour passes WCAG AA on its background.

Deliberately absent: **green**. On RunPapers, colour never signals "verified" (verification levels are internal),
and there are no traffic-light badges.

## Type
| Role | Font | Notes |
|---|---|---|
| Interface, headings, the name | Atkinson Hyperlegible Next (Bold 700 for headings and the logo, Regular 400 for text) | 17-18 px body, line length under 75 characters |
| Paper titles, quotes from papers | Newsreader (Regular 400, optical size on) | the paper's voice |
| Prompts, DOIs, commands | Atkinson Hyperlegible Mono (Medium 500) | the copy-prompt box |

Self-host the `.woff2` files (no Google Fonts requests: visitors' addresses never leave our site).

## Using the logo
- Clear space around the logo: the height of the triangle on every side. Smallest size: 20 px tall on screen
  (use the mark alone, or `favicon.svg`, below that).
- On photos or dark colours use `-reverse` or `-white`. Don't recolour the triangle in other colours, add
  shadows, outlines or gradients, or stretch it.
- The RunPapers name and logo identify this project. The code in this repository is MIT licensed; please don't
  use the logo in a way that suggests RunPapers made or endorses something it didn't.

## Rebuilding
`uv run brand/tools/build_brand.py` (from the repository root) regenerates every file from `color/palette.json` and
the fonts. Change a hex value there and rerun to recolour everything at once.
