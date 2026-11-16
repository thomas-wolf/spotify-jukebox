"""Geometry for the display: rotation, covered edges, where the cover and the text go. Pure functions."""
from __future__ import annotations

from dataclasses import dataclass

ROTATIONS = (0, 90, 180, 270)
MIN_VISIBLE = 48          # smaller visible areas make no sense


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def logical_size(width: int, height: int, rotation: int) -> tuple[int, int]:
    """Size of the picture as you look at it. `width` x `height` is the panel's native (portrait) size."""
    if rotation not in ROTATIONS:
        raise ValueError(f"rotation must be one of {ROTATIONS}")
    return (height, width) if rotation in (90, 270) else (width, height)


def visible_rect(lw: int, lh: int, left: int, top: int, right: int, bottom: int) -> Rect:
    """The part of the picture that is not hidden by the housing. Margins are in pixels, as you look at it."""
    if min(left, top, right, bottom) < 0:
        raise ValueError("margins must not be negative")
    rect = Rect(left, top, lw - left - right, lh - top - bottom)
    if rect.w < MIN_VISIBLE or rect.h < MIN_VISIBLE:
        raise ValueError(f"margins leave only {rect.w}x{rect.h} pixels visible")
    return rect


def plan(vis: Rect, layout: str = "auto", cover_side: str = "left", pad: int = 8) -> tuple[Rect, Rect | None]:
    """Return (cover box, text box or None).

    The cover box is a square on one side of the visible area; the rest is for text. `layout`:
    "cover": the cover alone fills the visible area; "overlay": the same, with title and artist drawn over it; "split": square cover plus text; "auto": split when the
    leftover space is big enough for text, otherwise cover alone.
    """
    if layout in ("cover", "overlay"):          # overlay: the renderer draws the text onto the cover
        return vis, None
    landscape = vis.w >= vis.h
    side = vis.h if landscape else vis.w
    rest = (vis.w - side) if landscape else (vis.h - side)
    enough = rest >= (100 if landscape else 64)
    if layout == "auto" and not enough:
        return vis, None
    if rest < 32:
        return vis, None
    if landscape:
        if cover_side == "right":
            cover = Rect(vis.x + vis.w - side, vis.y, side, side)
            text = Rect(vis.x + pad, vis.y + pad, rest - 2 * pad, vis.h - 2 * pad)
        else:
            cover = Rect(vis.x, vis.y, side, side)
            text = Rect(vis.x + side + pad, vis.y + pad, rest - 2 * pad, vis.h - 2 * pad)
    else:
        if cover_side == "bottom":
            cover = Rect(vis.x, vis.y + vis.h - side, side, side)
            text = Rect(vis.x + pad, vis.y + pad, vis.w - 2 * pad, rest - 2 * pad)
        else:
            cover = Rect(vis.x, vis.y, side, side)
            text = Rect(vis.x + pad, vis.y + side + pad, vis.w - 2 * pad, rest - 2 * pad)
    return cover, text


def fit_box(src_w: int, src_h: int, box_w: int, box_h: int, mode: str) -> tuple[int, int, int, int]:
    """Scale a picture into a box: (new width, new height, x offset, y offset) relative to the box.

    "contain": whole picture visible, empty bars where the aspect ratio differs (offsets >= 0).
    "cover": the box is filled, the picture is cropped (offsets <= 0).
    """
    sx, sy = box_w / src_w, box_h / src_h
    scale = max(sx, sy) if mode == "cover" else min(sx, sy)
    nw, nh = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    return nw, nh, (box_w - nw) // 2, (box_h - nh) // 2


def wrap(text: str, measure, max_width: int, max_lines: int) -> list[str]:
    """Break text into lines no wider than max_width (`measure(str) -> width`), ending in an ellipsis on overflow."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if measure(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and measure(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    out = []
    for line in lines:                       # a single word wider than the box: cut it
        while len(line) > 1 and measure(line) > max_width:
            line = line[:-1]
        out.append(line)
    return out
