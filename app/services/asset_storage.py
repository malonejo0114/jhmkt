from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def save_asset(content_unit_id: str, slide_no: int, image_bytes: bytes) -> str:
    settings = get_settings()

    if settings.storage_mode == "gcs":
        return _save_to_gcs(content_unit_id, slide_no, image_bytes)
    return _save_to_local(content_unit_id, slide_no, image_bytes)


def _save_to_local(content_unit_id: str, slide_no: int, image_bytes: bytes) -> str:
    settings = get_settings()
    root = Path(settings.local_asset_dir).expanduser().resolve()
    target_dir = root / content_unit_id
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"slide_{slide_no:02d}.jpg"
    file_path.write_bytes(image_bytes)
    return str(file_path)


def _save_to_gcs(content_unit_id: str, slide_no: int, image_bytes: bytes) -> str:
    settings = get_settings()
    if not settings.gcs_bucket:
        raise ValueError("storage_mode=gcs 인 경우 gcs_bucket 설정이 필요합니다.")

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(settings.gcs_bucket)
    object_name = f"carousel/{content_unit_id}/slide_{slide_no:02d}.jpg"
    blob = bucket.blob(object_name)
    blob.upload_from_string(image_bytes, content_type="image/jpeg")
    return f"gs://{settings.gcs_bucket}/{object_name}"
