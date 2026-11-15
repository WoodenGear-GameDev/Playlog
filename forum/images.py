from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 1600
MAX_PIXELS = 25_000_000
QUALITY = 82


class ImageRejected(ValueError):
    """Изображение не подходит; текст ошибки можно показать пользователю."""


def compress_post_image(uploaded_file):
    """Уменьшает изображение, убирает метаданные и возвращает WebP-файл."""
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as img:
            if img.width * img.height > MAX_PIXELS:
                raise ImageRejected('Слишком большое изображение (больше 25 мегапикселей).')
            if img.format == 'JPEG':
                # Облегчает чтение больших фотографий: сразу в уменьшенном размере
                img.draft('RGB', (MAX_SIDE, MAX_SIDE))
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'RGBA'):
                has_alpha = img.mode in ('LA', 'PA') or 'transparency' in img.info
                img = img.convert('RGBA' if has_alpha else 'RGB')
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format='WEBP', quality=QUALITY)
    except ImageRejected:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageRejected('Не удалось обработать изображение.') from exc
    return ContentFile(buffer.getvalue(), name='image.webp')