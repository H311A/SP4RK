import io

from PIL import Image, ImageDraw

from app.config import settings

FADE_FRACTION = 0.32
VIGNETTE_STRENGTH = 0.32
BORDER_WIDTH = 3
BORDER_COLOR = (255, 255, 255, 70)


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _cover_crop(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = image.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_w = max(1, int(src_h * target_ratio))
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:
        new_h = max(1, int(src_w / target_ratio))
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)

    return image.crop(box).resize((target_w, target_h), Image.LANCZOS)


def _apply_left_corner_fade(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    width, height = image.size
    fade_width = max(1, int(width * FADE_FRACTION))

    alpha = image.getchannel("A")
    pixels = alpha.load()
    for x in range(fade_width):
        mult = _smoothstep(x / fade_width)
        for y in range(height):
            pixels[x, y] = int(pixels[x, y] * mult)
    image.putalpha(alpha)
    return image


def _apply_vignette(image: Image.Image, strength: float = VIGNETTE_STRENGTH) -> Image.Image:
    width, height = image.size
    gradient = Image.radial_gradient("L").resize((width, height))
    darken_mask = gradient.point(lambda v: int(v * strength))

    rgb = image.convert("RGB")
    black = Image.new("RGB", image.size, (0, 0, 0))
    darkened = Image.composite(black, rgb, darken_mask).convert("RGBA")
    darkened.putalpha(image.getchannel("A"))
    return darkened


def _apply_frame(image: Image.Image) -> Image.Image:
    framed = image.copy()
    draw = ImageDraw.Draw(framed, "RGBA")
    width, height = framed.size
    inset = BORDER_WIDTH // 2
    draw.rectangle(
        (inset, inset, width - 1 - inset, height - 1 - inset),
        outline=BORDER_COLOR,
        width=BORDER_WIDTH,
    )
    return framed


def fit_banner(raw_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(raw_bytes)) as source:
        source.load()
        rgba = source.convert("RGBA")
        fitted = _cover_crop(rgba, settings.banner_width, settings.banner_height)
        faded = _apply_left_corner_fade(fitted)
        vignetted = _apply_vignette(faded)
        framed = _apply_frame(vignetted)

        buffer = io.BytesIO()
        framed.save(buffer, format="PNG")
        return buffer.getvalue()
