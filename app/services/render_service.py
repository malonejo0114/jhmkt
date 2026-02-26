from __future__ import annotations

import io
import textwrap
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentUnit, RenderedAsset
from app.services.asset_storage import save_asset
from app.services.hash_utils import sha256_hex
from app.services.stock_image_service import fetch_background

CANVAS_W = 1080
CANVAS_H = 1350
SAFE_LEFT = 80
SAFE_RIGHT = 80
SAFE_TOP = 120
SAFE_BOTTOM = 160

TITLE_MAX_LINES = 2
BODY_MAX_LINES = 6

FONT_CANDIDATES_BY_STYLE: dict[str, list[str]] = {
    "sans": [
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",
        "/Library/Fonts/NotoSansKR-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ],
    "serif": [
        "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf",
        "/Library/Fonts/NotoSerifKR-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    ],
    "mono": [
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/Library/Fonts/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ],
}


def _load_font(size: int, font_style: str = "sans") -> ImageFont.ImageFont:
    candidates = FONT_CANDIDATES_BY_STYLE.get(font_style, FONT_CANDIDATES_BY_STYLE["sans"])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_w: int,
    *,
    start_size: int,
    min_size: int,
    max_lines: int,
    font_style: str,
) -> tuple[list[str], ImageFont.ImageFont]:
    size = start_size
    while size >= min_size:
        font = _load_font(size, font_style=font_style)
        avg_char_width = max(draw.textlength("가", font=font), 10)
        width_chars = max(8, int(box_w / avg_char_width))
        wrapped = textwrap.wrap(text, width=width_chars)
        if len(wrapped) <= max_lines:
            return wrapped, font
        size -= 2

    font = _load_font(min_size, font_style=font_style)
    avg_char_width = max(draw.textlength("가", font=font), 10)
    width_chars = max(8, int(box_w / avg_char_width))
    wrapped = textwrap.wrap(text, width=width_chars)[:max_lines]
    if wrapped:
        wrapped[-1] = wrapped[-1][: max(1, len(wrapped[-1]) - 1)] + "…"
    return wrapped, font


def _crop_fill_canvas(img: Image.Image) -> Image.Image:
    src_w, src_h = img.size
    src_ratio = src_w / max(1, src_h)
    dst_ratio = CANVAS_W / CANVAS_H

    if src_ratio > dst_ratio:
        new_h = CANVAS_H
        new_w = int(src_w * (new_h / src_h))
    else:
        new_w = CANVAS_W
        new_h = int(src_h * (new_w / src_w))

    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - CANVAS_W) // 2
    top = (new_h - CANVAS_H) // 2
    return resized.crop((left, top, left + CANVAS_W, top + CANVAS_H))


def _prepare_background(background_bytes: bytes, slide_no: int) -> Image.Image | None:
    try:
        base = Image.open(io.BytesIO(background_bytes))
    except Exception:
        return None

    base = ImageOps.exif_transpose(base).convert("RGB")
    base = _crop_fill_canvas(base)
    gray = ImageOps.grayscale(base).convert("RGB")
    gray = ImageEnhance.Contrast(gray).enhance(0.93)
    gray = gray.filter(ImageFilter.GaussianBlur(radius=1.1))

    tint_palette = [
        (207, 224, 238),
        (198, 217, 232),
        (214, 228, 238),
    ]
    tint = Image.new("RGB", (CANVAS_W, CANVAS_H), tint_palette[(slide_no - 1) % len(tint_palette)])
    return Image.blend(gray, tint, alpha=0.24)


def _draw_highlight_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    x: int,
    y: int,
    font: ImageFont.ImageFont,
    default_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
) -> None:
    words = text.split()
    if len(words) < 2:
        draw.text((x, y), text, fill=default_color, font=font)
        return

    highlight = max(words, key=len)
    before, sep, after = text.partition(highlight)
    if not sep:
        draw.text((x, y), text, fill=default_color, font=font)
        return

    cursor_x = x
    if before:
        draw.text((cursor_x, y), before, fill=default_color, font=font)
        cursor_x += int(draw.textlength(before, font=font))
    draw.text((cursor_x, y), highlight, fill=accent_color, font=font)
    cursor_x += int(draw.textlength(highlight, font=font))
    if after:
        draw.text((cursor_x, y), after, fill=default_color, font=font)


def _render_slide_classic(
    slide_no: int,
    title: str,
    body: str,
    *,
    font_style: str,
    background_bytes: bytes | None,
) -> bytes:
    bg_palette = [
        (244, 247, 240),
        (234, 243, 254),
        (246, 238, 232),
    ]
    accent_palette = [
        (15, 48, 63),
        (24, 57, 102),
        (88, 52, 28),
    ]

    bg = bg_palette[(slide_no - 1) % len(bg_palette)]
    accent = accent_palette[(slide_no - 1) % len(accent_palette)]

    prepared_bg = _prepare_background(background_bytes, slide_no) if background_bytes else None
    img = prepared_bg if prepared_bg else Image.new("RGB", (CANVAS_W, CANVAS_H), bg)
    img = img.convert("RGBA")

    # Text readability layer.
    overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (247, 251, 255, 188))
    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")

    draw = ImageDraw.Draw(img)

    # Decorative stripe for intentional visual identity.
    draw.rounded_rectangle([(SAFE_LEFT, 70), (CANVAS_W - SAFE_RIGHT, 95)], radius=12, fill=accent)

    box_w = CANVAS_W - SAFE_LEFT - SAFE_RIGHT
    title_lines, title_font = _fit_text_box(
        draw,
        title,
        box_w,
        start_size=64,
        min_size=44,
        max_lines=TITLE_MAX_LINES,
        font_style=font_style,
    )
    body_lines, body_font = _fit_text_box(
        draw,
        body,
        box_w,
        start_size=42,
        min_size=30,
        max_lines=BODY_MAX_LINES,
        font_style=font_style,
    )

    y = SAFE_TOP
    for line in title_lines:
        draw.text((SAFE_LEFT, y), line, fill=accent, font=title_font)
        y += int(title_font.size * 1.25)

    y += 36
    body_color = (40, 40, 40)
    for line in body_lines:
        draw.text((SAFE_LEFT, y), line, fill=body_color, font=body_font)
        y += int(body_font.size * 1.45)

    footer = f"{slide_no:02d}"
    draw.text(
        (CANVAS_W - SAFE_RIGHT - 60, CANVAS_H - SAFE_BOTTOM + 40),
        footer,
        fill=accent,
        font=_load_font(30, font_style=font_style),
    )

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _render_slide_campaign(
    slide_no: int,
    title: str,
    body: str,
    *,
    font_style: str,
    background_bytes: bytes | None,
) -> bytes:
    base_bg = (18, 22, 28)
    prepared_bg = _prepare_background(background_bytes, slide_no) if background_bytes else None
    if prepared_bg is None:
        img = Image.new("RGB", (CANVAS_W, CANVAS_H), base_bg)
    else:
        img = prepared_bg
    img = img.convert("RGBA")

    dark_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 115))
    img = Image.alpha_composite(img, dark_layer)

    grad = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grad, "RGBA")
    for i in range(560):
        alpha = min(255, int(230 * (i / 560)))
        y = CANVAS_H - 560 + i
        gdraw.rectangle((0, y, CANVAS_W, y + 1), fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad).convert("RGB")
    draw = ImageDraw.Draw(img)

    accent = (255, 176, 34)
    white = (250, 250, 250)

    draw.rectangle((SAFE_LEFT - 34, SAFE_TOP + 120, SAFE_LEFT - 24, SAFE_TOP + 310), fill=white)

    box_w = CANVAS_W - SAFE_LEFT - SAFE_RIGHT
    title_lines, title_font = _fit_text_box(
        draw,
        title,
        box_w,
        start_size=74,
        min_size=46,
        max_lines=3,
        font_style=font_style,
    )
    body_lines, body_font = _fit_text_box(
        draw,
        body,
        box_w,
        start_size=54,
        min_size=34,
        max_lines=5,
        font_style=font_style,
    )

    y = SAFE_TOP + 120
    kicker = f"슬라이드 {slide_no:02d}"
    draw.text((SAFE_LEFT, y - 70), kicker, fill=white, font=_load_font(34, font_style=font_style))
    for line in title_lines:
        _draw_highlight_line(
            draw,
            line,
            x=SAFE_LEFT,
            y=y,
            font=title_font,
            default_color=white,
            accent_color=accent,
        )
        y += int(title_font.size * 1.2)

    y += 18
    draw.rectangle((SAFE_LEFT, y, CANVAS_W - SAFE_RIGHT, y + 5), fill=white)
    y += 28

    for line in body_lines:
        draw.text((SAFE_LEFT, y), line, fill=white, font=body_font)
        y += int(body_font.size * 1.45)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _render_slide(
    slide_no: int,
    title: str,
    body: str,
    *,
    font_style: str,
    background_bytes: bytes | None,
    template_style: str,
) -> bytes:
    if template_style == "campaign":
        return _render_slide_campaign(
            slide_no,
            title,
            body,
            font_style=font_style,
            background_bytes=background_bytes,
        )
    return _render_slide_classic(
        slide_no,
        title,
        body,
        font_style=font_style,
        background_bytes=background_bytes,
    )


def ensure_rendered_assets(db: Session, content_unit_id: str) -> list[RenderedAsset]:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    existing = (
        db.execute(
            select(RenderedAsset)
            .where(RenderedAsset.content_unit_id == unit.id)
            .order_by(RenderedAsset.slide_no.asc())
        )
        .scalars()
        .all()
    )
    if existing:
        return existing

    render_options: dict[str, Any] = {}
    if isinstance(unit.slide_script, dict):
        render_options = unit.slide_script.get("render_options", {})
    slides = unit.slide_script.get("slides", []) if isinstance(unit.slide_script, dict) else []
    if not slides:
        raise ValueError("slide_script.slides 가 비어 있습니다.")

    font_style = str(render_options.get("font_style", "sans")).lower()
    if font_style not in FONT_CANDIDATES_BY_STYLE:
        font_style = "sans"

    background_mode = str(render_options.get("background_mode", "google_free")).lower()
    template_style = str(render_options.get("template_style", "campaign")).lower()
    if template_style not in {"campaign", "classic"}:
        template_style = "campaign"

    background_bytes = fetch_background(unit.topic, background_mode=background_mode)

    inserted: list[RenderedAsset] = []
    for slide in slides:
        slide_no = int(slide.get("slide_no", len(inserted) + 1))
        title = str(slide.get("title", ""))
        body = str(slide.get("body", ""))
        image_bytes = _render_slide(
            slide_no,
            title,
            body,
            font_style=font_style,
            background_bytes=background_bytes,
            template_style=template_style,
        )
        uri = save_asset(str(unit.id), slide_no, image_bytes)
        checksum = sha256_hex(image_bytes.hex())

        asset = RenderedAsset(
            content_unit_id=unit.id,
            slide_no=slide_no,
            gcs_uri=uri,
            width=CANVAS_W,
            height=CANVAS_H,
            checksum_sha256=checksum,
        )
        db.add(asset)
        inserted.append(asset)

    db.commit()
    for asset in inserted:
        db.refresh(asset)
    return inserted
