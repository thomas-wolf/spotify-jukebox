"""Draws the picture for the display with Pillow (apt: python3-pil). Imported only when a display is used."""
from __future__ import annotations

import io
import urllib.request

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .layout import Rect, fit_box, plan, visible_rect, wrap
from .settings import DisplaySettings

MAX_COVER_BYTES = 8 * 1024 * 1024


def fetch_cover(url: str, timeout: float = 6.0) -> Image.Image:
    if url.startswith("/") or url.startswith("file://"):               # a picture file on this box
        img = Image.open(url[len("file://"):] if url.startswith("file://") else url)
        img.load()
        return img.convert("RGB")
    if not url.startswith(("http://", "https://")):
        raise ValueError("cover must be a file path or an http(s) URL")
    with urllib.request.urlopen(url, timeout=timeout) as resp:      # noqa: S310 (scheme checked above)
        data = resp.read(MAX_COVER_BYTES + 1)
    if len(data) > MAX_COVER_BYTES:
        raise ValueError("cover too large")
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


# Pillow's built-in font lacks glyphs such as the German sharp s, so look for a system font first.
SYSTEM_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)


def _font(path: str, size: int):
    for candidate in ([path] if path else []) + list(SYSTEM_FONTS):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)     # scalable with Pillow >= 10.1 and FreeType
    except TypeError:
        return ImageFont.load_default()


def _luma(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


class Renderer:
    def __init__(self, s: DisplaySettings) -> None:
        self.s = s
        self.lw, self.lh = s.logical
        self.vis = visible_rect(self.lw, self.lh, s.margin_left, s.margin_top, s.margin_right, s.margin_bottom)
        self.cover_box, self.text_box = plan(self.vis, s.layout, s.cover_side)
        self.title_font = _font(s.font, s.title_size)
        self.artist_font = _font(s.font, s.artist_size)

    # -- background ----------------------------------------------------------
    def _background(self, cover: Image.Image | None) -> Image.Image:
        s = self.s
        if s.background.startswith("#"):
            return Image.new("RGB", (self.lw, self.lh), s.background)
        if cover is None:
            return Image.new("RGB", (self.lw, self.lh), (0, 0, 0))
        if s.background == "blur":
            nw, nh, ox, oy = fit_box(*cover.size, self.lw, self.lh, "cover")
            big = cover.resize((nw, nh)).crop((-ox, -oy, -ox + self.lw, -oy + self.lh))
            return ImageEnhance.Brightness(big.filter(ImageFilter.GaussianBlur(14))).enhance(0.45)
        avg = cover.resize((1, 1), Image.BOX).getpixel((0, 0))
        return Image.new("RGB", (self.lw, self.lh), tuple(int(c * 0.45) for c in avg))

    # -- picture -------------------------------------------------------------
    def render(self, cover: Image.Image | None, title: str = "", artist: str = "") -> Image.Image:
        img = self._background(cover)
        draw = ImageDraw.Draw(img)
        bg = img.getpixel((self.vis.x + self.vis.w // 2, self.vis.y + self.vis.h // 2)) if self.s.background != "blur" \
            else img.resize((1, 1), Image.BOX).getpixel((0, 0))
        ink = (0, 0, 0) if _luma(bg) > 140 else (255, 255, 255)
        sub = tuple(int(c * 0.7 + b * 0.3) for c, b in zip(ink, bg))     # softer colour for the artist
        if cover is not None:
            self._paste_cover(img, cover)
            if self.s.layout == "overlay":
                self._overlay(img, title, artist)
            elif self.text_box is not None:
                self._text(draw, self.text_box, title, artist, ink, sub, anchor_left=True)
        elif title or artist:
            self._text(draw, self.vis, title, artist, ink, sub, anchor_left=False)
        return img

    def _paste_cover(self, img: Image.Image, cover: Image.Image) -> None:
        box: Rect = self.cover_box
        fit = "cover" if self.s.layout == "overlay" else self.s.cover_fit   # overlay: the cover fills the screen
        nw, nh, ox, oy = fit_box(*cover.size, box.w, box.h, fit)
        scaled = cover.resize((nw, nh), Image.LANCZOS)
        if fit == "cover":
            img.paste(scaled.crop((-ox, -oy, -ox + box.w, -oy + box.h)), (box.x, box.y))
        else:
            img.paste(scaled, (box.x + ox, box.y + oy))

    def _overlay(self, img: Image.Image, title: str, artist: str) -> None:
        """Title and artist over the lower part of the cover, on a dark gradient so that they stay readable."""
        if not (title or artist):
            return
        v, pad = self.vis, 8
        draw = ImageDraw.Draw(img)
        t_lines = wrap(title, lambda t: draw.textlength(t, font=self.title_font), v.w - 2 * pad, 3) if title else []
        a_lines = wrap(artist, lambda t: draw.textlength(t, font=self.artist_font), v.w - 2 * pad, 2) if artist else []
        th, ah = self.s.title_size + 4, self.s.artist_size + 3
        text_h = len(t_lines) * th + len(a_lines) * ah + (4 if t_lines and a_lines else 0)
        fade = 28
        band_h = min(v.h, text_h + 2 * pad + fade)
        top = v.y + v.h - band_h
        mask = Image.new("L", (v.w, band_h))
        md = ImageDraw.Draw(mask)
        for row in range(band_h):                                   # transparent at the top, 80% dark at the bottom
            alpha = int(204 * min(1.0, row / fade)) if fade else 204
            md.line((0, row, v.w, row), fill=alpha)
        img.paste(Image.new("RGB", (v.w, band_h), (0, 0, 0)), (v.x, top), mask)
        y = v.y + v.h - pad - text_h
        for lines, font, step, color in ((t_lines, self.title_font, th, (255, 255, 255)),
                                         (a_lines, self.artist_font, ah, (215, 215, 215))):
            for line in lines:
                draw.text((v.x + pad + 1, y + 1), line, font=font, fill=(0, 0, 0))   # shadow
                draw.text((v.x + pad, y), line, font=font, fill=color)
                y += step
            y += 4

    def _text(self, draw, box: Rect, title, artist, ink, sub, anchor_left: bool) -> None:
        def measure(font):
            return lambda t: draw.textlength(t, font=font)
        t_lines = wrap(title, measure(self.title_font), box.w, 4) if title else []
        a_lines = wrap(artist, measure(self.artist_font), box.w, 2) if artist else []
        th, ah = self.s.title_size + 4, self.s.artist_size + 3
        total = len(t_lines) * th + len(a_lines) * ah + (6 if t_lines and a_lines else 0)
        y = box.y + max(0, (box.h - total) // 2)
        for lines, font, step, color in ((t_lines, self.title_font, th, ink), (a_lines, self.artist_font, ah, sub)):
            for line in lines:
                w = draw.textlength(line, font=font)
                x = box.x if anchor_left else box.x + (box.w - w) / 2
                draw.text((x, y), line, font=font, fill=color)
                y += step
            y += 6

    def idle(self, picture: Image.Image) -> Image.Image:
        """A picture for boot and idle: placed in the visible area, the rest in the picture's average colour."""
        img = self._background(picture)
        v = self.vis
        nw, nh, ox, oy = fit_box(*picture.size, v.w, v.h, self.s.idle_fit)
        scaled = picture.resize((nw, nh), Image.LANCZOS)
        if self.s.idle_fit == "cover":
            img.paste(scaled.crop((-ox, -oy, -ox + v.w, -oy + v.h)), (v.x, v.y))
        else:
            img.paste(scaled, (v.x + ox, v.y + oy))
        return img

    def blank(self) -> Image.Image:
        return Image.new("RGB", (self.lw, self.lh), (0, 0, 0))

    def test_pattern(self, cover: Image.Image | None = None) -> Image.Image:
        """Calibration picture: red = edge of the panel, green = visible area (after margins)."""
        base = self.render(cover or _sample_cover(), "Title of the track", "Artist name")
        d = ImageDraw.Draw(base)
        d.rectangle((0, 0, self.lw - 1, self.lh - 1), outline=(255, 0, 0), width=2)
        v = self.vis
        d.rectangle((v.x, v.y, v.x + v.w - 1, v.y + v.h - 1), outline=(0, 255, 0), width=1)
        f = _font("", 12)
        for label, xy in (("TL", (4, 4)), ("TR", (self.lw - 22, 4)), ("BL", (4, self.lh - 18)),
                          ("BR", (self.lw - 22, self.lh - 18))):
            d.text(xy, label, font=f, fill=(255, 255, 0))
        d.text((self.lw // 2 - 40, 4), f"{self.lw}x{self.lh} rot {self.s.rotation}", font=f, fill=(255, 255, 0))
        return base


def _sample_cover() -> Image.Image:
    img = Image.new("RGB", (400, 300))                  # 4:3 like many covers
    d = ImageDraw.Draw(img)
    for i in range(300):
        d.line((0, i, 400, i), fill=(40 + i // 3, 90, 200 - i // 3))
    d.ellipse((100, 50, 300, 250), outline=(255, 255, 255), width=6)
    return img
