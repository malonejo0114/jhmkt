from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentUnit, RenderedAsset
from app.services.asset_storage import save_asset
from app.services.hash_utils import sha256_hex

CANVAS_W = 1080
CANVAS_H = 1350
SAFE_LEFT = 80
SAFE_RIGHT = 80
SAFE_TOP = 120
SAFE_BOTTOM = 160

TITLE_MAX_LINES = 2
BODY_MAX_LINES = 6


@dataclass
class FontPack:
    title: ImageFont.ImageFont
    body: ImageFont.ImageFont


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",
        "/Library/Fonts/NotoSansKR-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text_box(draw: ImageDraw.ImageDraw, text: str, box_w: int, *, start_size: int, min_size: int, max_lines: int) -> tuple[list[str], ImageFont.ImageFont]:
    size = start_size
    while size >= min_size:
        font = _load_font(size)
        avg_char_width = max(draw.textlength("가", font=font), 10)
        width_chars = max(8, int(box_w / avg_char_width))
        wrapped = textwrap.wrap(text, width=width_chars)
        if len(wrapped) <= max_lines:
            return wrapped, font
        size -= 2

    font = _load_font(min_size)
    avg_char_width = max(draw.textlength("가", font=font), 10)
    width_chars = max(8, int(box_w / avg_char_width))
    wrapped = textwrap.wrap(text, width=width_chars)[:max_lines]
    if wrapped:
        wrapped[-1] = wrapped[-1][: max(1, len(wrapped[-1]) - 1)] + "…"
    return wrapped, font


def _render_slide(slide_no: int, title: str, body: str) -> bytes:
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

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), bg)
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
    )
    body_lines, body_font = _fit_text_box(
        draw,
        body,
        box_w,
        start_size=42,
        min_size=30,
        max_lines=BODY_MAX_LINES,
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
    draw.text((CANVAS_W - SAFE_RIGHT - 60, CANVAS_H - SAFE_BOTTOM + 40), footer, fill=accent, font=_load_font(30))

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


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

    slides = unit.slide_script.get("slides", []) if isinstance(unit.slide_script, dict) else []
    if not slides:
        raise ValueError("slide_script.slides 가 비어 있습니다.")

    inserted: list[RenderedAsset] = []
    for slide in slides:
        slide_no = int(slide.get("slide_no", len(inserted) + 1))
        title = str(slide.get("title", ""))
        body = str(slide.get("body", ""))
        image_bytes = _render_slide(slide_no, title, body)
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
