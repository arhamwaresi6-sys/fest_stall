from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, UnidentifiedImageError


def save_image(upload, folder):
    if not upload or not upload.filename:
        return None
    try:
        image = Image.open(upload.stream)
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Upload a JPEG, PNG, or WebP image.")
        if image.width * image.height > 20_000_000:
            raise ValueError("Image dimensions are too large. Use an image under 20 megapixels.")
        image.verify()
        upload.stream.seek(0)
        image = Image.open(upload.stream)
        image.thumbnail((1600, 1600))
        if image.mode != "RGB":
            image = image.convert("RGB")
        filename = f"{uuid4().hex}.jpg"
        relative = f"{folder}/{filename}"
        destination = Path(current_app.instance_path) / "uploads" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="JPEG", quality=86, optimize=True)
        return relative
    except ValueError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("That image could not be read. Choose a valid JPEG, PNG, or WebP file.") from exc
