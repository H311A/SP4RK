import io

from PIL import Image

from app.bot.banners import storage
from app.bot.banners.processor import fit_banner


def process_and_store(raw_bytes: bytes) -> tuple[str, int, int]:
    fitted = fit_banner(raw_bytes)
    path = storage.save_banner(fitted)
    with Image.open(io.BytesIO(fitted)) as img:
        width, height = img.size
    return path, width, height


def copy_banner(source_path: str | None) -> str | None:
    if not source_path:
        return None
    data = storage.read_banner(source_path)
    if data is None:
        return None
    return storage.save_banner(data)


def delete_banner(path: str | None) -> None:
    storage.delete_banner(path)


def read_banner(path: str | None) -> bytes | None:
    return storage.read_banner(path)
