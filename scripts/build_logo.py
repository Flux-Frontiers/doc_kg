#!/usr/bin/env python3
"""Draw the DocKG logo in Art Techno and write every size the repo uses.

The mark is a page whose content is its own graph. The die is the document,
the three gold nodes are its sections, and each section holds a chain of
copper chunks: CONTAINS down the trunk, NEXT along each row. The palette,
drawing helpers and outlined lettering come from the Art Techno brand build,
so the SVGs render the same everywhere.

Usage::

    python scripts/build_logo.py

Needs ``fonttools`` and Pillow, Google Chrome for the PNG renders, and a clone
of https://github.com/Flux-Frontiers/art_techno beside this repo. Set ``CHROME``
to the browser binary if it is not at the default macOS path.

Writes, under ``assets/``:

- ``dockg_logo.svg`` and ``dockg_logo.png``: the square mark (1024 px PNG)
- ``dockg_icon.svg``: the mark reduced for 64 px and below
- ``dockg_banner.svg`` and ``dockg_banner.png``
- ``dockg_logo_{256,128}.png`` from the mark and ``dockg_logo_{64,32}.png``
  from the icon
"""

import importlib.util
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
AT_BUILD = ROOT.parent / "art_techno" / "docs" / "brand" / "build.py"

_spec = importlib.util.spec_from_file_location("at_build", AT_BUILD)
at = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(at)

f, line, pad, via, diamond, clipped_rect = (
    at.f,
    at.line,
    at.pad,
    at.via,
    at.diamond,
    at.clipped_rect,
)
OBSIDIAN, PANEL, COPPER, GOLD, GREEN, MINT, SILK = (
    at.OBSIDIAN,
    at.PANEL,
    at.COPPER,
    at.GOLD,
    at.GREEN,
    at.MINT,
    at.SILK,
)

NAME = "DOCKG"
PART = "FLUX-FRONTIERS | DOC-KG"


def rect(
    x: float, y: float, w: float, h: float, fill: str, stroke: str = "", width: float = 0
) -> str:
    s = f' stroke="{stroke}" stroke-width="{f(width)}"' if stroke else ""
    return f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="{fill}"{s}/>'


def die(x: float, y: float, s: float, core: str) -> str:
    """A square green die in a gold line, centered on ``x, y``.

    :param x: Center x.
    :param y: Center y.
    :param s: Side length.
    :param core: Color of the square at its center.
    """
    return rect(x - s / 2, y - s / 2, s, s, GREEN, GOLD, s / 9) + rect(
        x - s / 6, y - s / 6, s / 3, s / 3, core
    )


def sheet(x: float, y: float, w: float, h: float, ear: float, width: float) -> str:
    """A portrait page with a folded top-right corner.

    :param x: Left edge.
    :param y: Top edge.
    :param w: Page width.
    :param h: Page height.
    :param ear: Size of the 45-degree fold.
    :param width: Stroke width of the page edge; the fold is half of it.
    """
    edge = [(x, y), (x + w - ear, y), (x + w, y + ear), (x + w, y + h), (x, y + h)]
    d = "M" + "L".join(f"{f(px)} {f(py)}" for px, py in edge) + "Z"
    fold = [(x + w - ear, y), (x + w - ear, y + ear), (x + w, y + ear)]
    return (
        f'<path d="{d}" fill="{PANEL}" stroke="{GOLD}" stroke-width="{f(width)}" stroke-linejoin="miter"/>'
        + line(fold, GOLD, width * 0.5)
    )


def outline() -> str:
    """The page and its outline on a 512 field, centered on x = 256."""
    out = [sheet(146, 62, 220, 300, 40, 5)]
    tx = 186
    # The trunk (CONTAINS) and the title line beside the document die.
    out.append(line([(tx, 112), (tx, 300), (tx + 28, 300)], GOLD, 6))
    out.append(line([(tx + 20, 112), (tx + 96, 112)], GOLD, 6) + via(tx + 104, 112, 8, GOLD))
    for ys in (172, 236, 300):
        # A section: its branch, its heading line, and its chunks in reading order.
        out.append(line([(tx, ys), (tx + 28, ys)], GOLD, 6))
        out.append(line([(tx + 52, ys), (tx + 132, ys)], GOLD, 5) + via(tx + 140, ys, 8, GOLD))
        yc = ys + 30
        out.append(line([(tx + 40, ys + 10), (tx + 40, yc), (tx + 64, yc)], COPPER, 4))
        for k in range(3):
            cx = tx + 71 + 38 * k
            if k:
                out.append(line([(cx - 31, yc), (cx - 7, yc)], COPPER, 4))
            out.append(via(cx, yc, 7.5, COPPER))
        out.append(pad(tx + 40, ys, 12, GOLD) + pad(tx + 40, ys, 5.3, GREEN))
    out.append(die(tx, 112, 32, SILK))
    return "".join(out)


def outline_small() -> str:
    """The outline reduced for 64 px and below: the page, the die, two sections."""
    out = [sheet(15, 9, 34, 46, 9, 3)]
    out.append(line([(25, 21), (25, 45), (32, 45)], GOLD, 3) + line([(25, 33), (32, 33)], GOLD, 3))
    out.append(pad(36, 33, 4, GOLD) + pad(36, 45, 4, GOLD))
    out.append(die(25, 20, 9, GOLD))
    return "".join(out)


def frame(w: float, h: float, inset: float, c: float, heavy: float) -> str:
    """Double frame with 45-degree corners and a green diamond at each corner.

    :param w: Canvas width.
    :param h: Canvas height.
    :param inset: Distance of the heavy line from the canvas edge.
    :param c: Corner cut of the heavy line.
    :param heavy: Stroke width of the heavy line.
    """
    out = [
        f'<path d="{clipped_rect(inset, inset, w - 2 * inset, h - 2 * inset, c)}" fill="none" stroke="{GOLD}" stroke-width="{f(heavy)}"/>',
        f'<path d="{clipped_rect(inset * 1.9, inset * 1.9, w - 3.8 * inset, h - 3.8 * inset, c * 0.75)}" fill="none" stroke="{GOLD}" stroke-width="{f(heavy * 0.4)}" stroke-opacity=".6"/>',
    ]
    d = inset * 1.45 + c * 0.4375
    for cx, cy in ((d, d), (w - d, d), (d, h - d), (w - d, h - d)):
        out.append(diamond(cx, cy, inset * 0.5, GREEN))
    return "".join(out)


def svg(w: int, h: int, title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f"<title>{title}</title>"
        f'<rect width="{w}" height="{h}" fill="{OBSIDIAN}"/>{body}</svg>\n'
    )


def mark(display, mono) -> str:
    """512 square mark: the outline, the name and the part line beneath."""
    body = frame(512, 512, 10, 26, 5) + outline()
    body += display.path(NAME, 256, 430, 40, 0.2, "middle", GOLD)
    body += mono.path(PART, 256, 462, 13.5, 0.3, "middle", MINT)
    return svg(512, 512, "DocKG mark, Art Techno", body)


def icon() -> str:
    """64 icon: the reduced outline in one heavy frame, no lettering."""
    body = f'<path d="{clipped_rect(2.5, 2.5, 59, 59, 7.5)}" fill="none" stroke="{GOLD}" stroke-width="3"/>'
    return svg(64, 64, "DocKG icon, Art Techno", body + outline_small())


def banner(display, mono) -> str:
    """1280 x 320 banner: the outline left, the name and part line right."""
    s = 0.78
    body = frame(1280, 320, 10, 18, 3)
    body += f'<g transform="translate({f(230 - 256 * s)} {f(160 - 212 * s)}) scale({s})">{outline()}</g>'
    cx = (450 + 1240) / 2
    body += display.path(NAME, cx, 172, 68, 0.2, "middle", GOLD)
    body += mono.path(PART, cx, 222, 17, 0.3, "middle", MINT)
    return svg(1280, 320, "DocKG banner, Art Techno", body)


def render(src: Path, out: Path, w: int, h: int) -> None:
    """Render the SVG ``src`` to ``out`` at ``w`` x ``h`` px with headless Chrome.

    :param src: SVG file; its ``width`` attribute sets the CSS width.
    :param out: PNG to write.
    :param w: Output width in px.
    :param h: Output height in px.
    """
    svg_w = int(src.read_text().split('width="', 1)[1].split('"', 1)[0])
    subprocess.run(
        [
            at.CHROME,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={svg_w},{svg_w * h // w}",
            f"--force-device-scale-factor={w / svg_w}",
            f"--screenshot={out}",
            src.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def resized(master: Path, dest: Path, px: int) -> None:
    Image.open(master).convert("RGB").resize((px, px), Image.LANCZOS).save(dest, optimize=True)


def main() -> None:
    at.fetch_fonts()
    display = at.Face(at.CACHE / "JosefinSans.ttf", weight=600)
    mono = at.Face(at.CACHE / "IBMPlexMono-Medium.ttf")

    assets = ROOT / "assets"
    mark_svg = assets / "dockg_logo.svg"
    icon_svg = assets / "dockg_icon.svg"
    banner_svg = assets / "dockg_banner.svg"
    mark_svg.write_text(mark(display, mono))
    icon_svg.write_text(icon())
    banner_svg.write_text(banner(display, mono))

    render(mark_svg, assets / "dockg_logo.png", 1024, 1024)
    render(banner_svg, assets / "dockg_banner.png", 2560, 640)
    with tempfile.TemporaryDirectory() as tmp:
        icon_png = Path(tmp) / "icon.png"
        render(icon_svg, icon_png, 1024, 1024)
        for px in (256, 128):
            resized(assets / "dockg_logo.png", assets / f"dockg_logo_{px}.png", px)
        for px in (64, 32):
            resized(icon_png, assets / f"dockg_logo_{px}.png", px)


if __name__ == "__main__":
    main()
