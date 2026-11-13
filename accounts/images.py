from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

AVATAR_MAX_SIDE = 512
AVATAR_QUALITY = 85


def compress_avatar(uploaded_file):
    """Уменьшает изображение, убирает метаданные и возвращает WebP-файл.

    При невозможности обработать файл бросает ValueError.
    """
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'RGBA'):
                has_alpha = img.mode in ('LA', 'PA') or 'transparency' in img.info
                img = img.convert('RGBA' if has_alpha else 'RGB')
            img.thumbnail(
                (AVATAR_MAX_SIDE, AVATAR_MAX_SIDE), Image.Resampling.LANCZOS
            )
            buffer = BytesIO()
            img.save(buffer, format='WEBP', quality=AVATAR_QUALITY)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError('Не удалось обработать изображение.') from exc
    return ContentFile(buffer.getvalue(), name='avatar.webp')