"""Table → PNG rendering for the shareable report images.

Deliberately uses **Pillow**, not matplotlib. matplotlib repeatedly crashed the
deployed app (build-time segfaults on bleeding-edge wheels; pyplot's global
state and the Agg/freetype C code are not thread-safe, so PNG exports rendering
concurrently in Streamlit's per-session ScriptRunner threads segfaulted the
whole process). Pillow is lighter and, guarded by the module-level lock below,
safe.

Living in its own module gives us real process-wide singletons for free: a
module is imported once and cached in sys.modules, so `_LOCK` and the font cache
are shared across every Streamlit session/rerun (a lock defined in the reran
app script would be recreated each time and protect nothing).
"""
from __future__ import annotations

import io
import os
import threading
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

MAROON = "#7A1F2B"
_FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

# freetype (used by Pillow for TrueType text) is not guaranteed thread-safe;
# serialize all rendering through one process-wide lock.
_LOCK = threading.Lock()

# Bold background colors mark subtotal / grand-total rows.
_BOLD_BGS = {"#F6D9D5", "#CDE8CF"}
_DARK = (31, 41, 55)
_RED = (192, 20, 60)
_GREEN = (19, 122, 58)
_WHITE = (255, 255, 255)


@lru_cache(maxsize=4)
def _fonts(size: int = 22):
    reg = ImageFont.truetype(os.path.join(_FONT_DIR, "DejaVuSans.ttf"), size)
    bold = ImageFont.truetype(os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"), size)
    return reg, bold


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def table_to_png(sdf, title="", subtitle="", row_bg=None, signed_cols=(),
                 header_bg=MAROON) -> bytes:
    """Render a string DataFrame to a readable PNG matching the dashboard look:
    maroon header, per-row shading (`row_bg`), red/green on `signed_cols` by
    sign. Thread-safe via `_LOCK`."""
    with _LOCK:
        return _render(sdf, title, subtitle, row_bg, signed_cols, header_bg)


def _render(sdf, title, subtitle, row_bg, signed_cols, header_bg) -> bytes:
    reg, bold = _fonts()
    cols = [str(c) for c in sdf.columns]
    ncol = len(cols)
    signed = set(signed_cols)
    pad_x, pad_y = 16, 11
    header_rgb = _hex(header_bg)

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def tw(text, f):
        return scratch.textlength(str(text), font=f)

    # Column widths: max of header (bold) and cells (regular), capped.
    col_w = []
    for j, c in enumerate(cols):
        w = tw(c, bold)
        for i in range(len(sdf)):
            w = max(w, tw(sdf.iat[i, j], reg))
        col_w.append(int(min(w, 460)) + 2 * pad_x)

    asc, desc = reg.getmetrics()
    row_h = asc + desc + 2 * pad_y
    title_txt = "\n".join(t for t in (title, subtitle) if t)
    title_h = row_h if title_txt else 0

    W = sum(col_w)
    H = title_h + row_h + len(sdf) * row_h  # title + header + rows
    img = Image.new("RGB", (W, H), _WHITE)
    d = ImageDraw.Draw(img)

    if title_txt:
        d.text((pad_x, pad_y), title_txt, font=bold, fill=_hex("7A1F2B"))

    def draw_row(cells, y0, bg, fonts, colors):
        d.rectangle([0, y0, W, y0 + row_h], fill=bg)
        x = 0
        for j in range(ncol):
            txt = str(cells[j])
            f = fonts[j]
            cx = x + (col_w[j] - tw(txt, f)) / 2      # centered
            d.text((cx, y0 + pad_y), txt, font=f, fill=colors[j])
            x += col_w[j]

    y = title_h
    draw_row(cols, y, header_rgb, [bold] * ncol, [_WHITE] * ncol)
    y += row_h
    for i in range(len(sdf)):
        bg = row_bg[i] if row_bg else "#FFFFFF"
        is_bold = bg in _BOLD_BGS
        fonts, colors = [], []
        for j, c in enumerate(cols):
            val = str(sdf.iat[i, j]).strip()
            if c in signed and val not in ("", "—"):
                colors.append(_RED if val.startswith("-") else _GREEN)
                fonts.append(bold)
            else:
                colors.append(_DARK)
                fonts.append(bold if is_bold else reg)
        draw_row([sdf.iat[i, j] for j in range(ncol)], y, _hex(bg), fonts, colors)
        y += row_h

    d.rectangle([0, title_h, W - 1, H - 1], outline=_hex("E7E1D6"))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
