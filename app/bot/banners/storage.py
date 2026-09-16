import os
import uuid

from app.config import settings


def _ensure_dir() -> None:
    os.makedirs(settings.banner_storage_dir, exist_ok=True)


def save_banner(image_bytes: bytes) -> str:
    _ensure_dir()
    filename = f"{uuid.uuid4().hex}.png"
    path = os.path.join(settings.banner_storage_dir, filename)
    with open(path, "wb") as fh:
        fh.write(image_bytes)
    return path


def read_banner(path: str | None) -> bytes | None:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def delete_banner(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
