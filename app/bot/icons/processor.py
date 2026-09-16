import io

from PIL import Image

ICON_SIZE = 128


def _cover_crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def fit_icon(raw_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(raw_bytes)) as source:
        source.load()
        rgba = source.convert("RGBA")
        square = _cover_crop_square(rgba)
        resized = square.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)

        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        return buffer.getvalue()
