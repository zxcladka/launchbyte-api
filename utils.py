import os
import uuid
import shutil
import hashlib
import re
import unicodedata
import mimetypes
import time
from pathlib import Path
from typing import Dict, Optional, List, Union, Any
from datetime import datetime, timedelta
from fastapi import UploadFile, HTTPException
from PIL import Image, ImageOps, ImageDraw, ImageFont
import io
import logging
import json
import bleach
from urllib.parse import urlparse, urljoin

from config import settings

# Налаштування логування
logger = logging.getLogger(__name__)


# ============ ФАЙЛОВІ УТИЛІТИ ============

def ensure_dir_exists(directory: str) -> None:
    """Створює директорію якщо вона не існує."""
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directory {directory}: {e}")
        raise


def generate_unique_filename(original_filename: str, prefix: str = "") -> str:
    """Генерує унікальне ім'я файлу з збереженням розширення."""
    if not original_filename:
        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:8]
        return f"{prefix}{timestamp}_{unique_id}"

    # Очищуємо ім'я файлу
    clean_name = sanitize_filename(original_filename)
    file_extension = Path(clean_name).suffix.lower()

    # Генеруємо унікальний ідентифікатор
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:8]

    # Формуємо ім'я: prefix_timestamp_uniqueid.ext
    name_part = Path(clean_name).stem[:50]  # Обмежуємо довжину
    unique_name = f"{prefix}{timestamp}_{unique_id}_{name_part}{file_extension}"

    return unique_name


def get_file_category(content_type: str, filename: str = "") -> str:
    """Визначає категорію файлу за MIME типом та розширенням."""
    if content_type.startswith('image/'):
        return 'images'
    elif content_type in [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/plain',
        'text/csv'
    ]:
        return 'documents'
    else:
        # Додаткова перевірка за розширенням
        if filename:
            ext = Path(filename).suffix.lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico']:
                return 'images'
            elif ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv', '.rtf']:
                return 'documents'
            elif ext in ['.mp4', '.avi', '.mov', '.webm', '.mp3', '.wav']:
                return 'media'

        return 'other'


def calculate_file_hash(file_content: bytes) -> str:
    """Обчислює SHA-256 хеш файлу з вмісту."""
    hash_sha256 = hashlib.sha256()
    try:
        hash_sha256.update(file_content)
        return hash_sha256.hexdigest()
    except Exception as e:
        logger.error(f"Failed to calculate file hash: {e}")
        return ""


def get_file_mime_type(filename: str, content: bytes) -> str:
    """Визначає MIME тип файлу за змістом та ім'ям."""
    # Спочатку перевіряємо за змістом (magic numbers)
    magic_numbers = {
        b'\xff\xd8\xff': 'image/jpeg',
        b'\x89PNG\r\n\x1a\n': 'image/png',
        b'GIF87a': 'image/gif',
        b'GIF89a': 'image/gif',
        b'RIFF': 'image/webp',  # Потрібна додаткова перевірка
        b'BM': 'image/bmp',
        b'%PDF': 'application/pdf',
        b'\x50\x4b\x03\x04': 'application/zip',  # Також для docx, xlsx
    }

    for magic, mime_type in magic_numbers.items():
        if content.startswith(magic):
            if magic == b'RIFF':
                # Додаткова перевірка для WEBP
                if b'WEBP' in content[:20]:
                    return 'image/webp'
                else:
                    return 'audio/wav'  # Альтернативний RIFF формат
            return mime_type

    # Якщо не вдалося визначити за змістом, використовуємо ім'я файлу
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or 'application/octet-stream'


async def save_uploaded_file(file: UploadFile, folder: Optional[str] = None) -> Dict[str, str]:
    """Зберігає завантажений файл на диск з покращеною обробкою."""
    try:
        # Читаємо вміст файлу
        file_content = await file.read()
        file_size = len(file_content)

        if file_size > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File size {file_size} exceeds maximum allowed size {settings.MAX_FILE_SIZE}"
            )

        # Визначаємо MIME тип
        actual_mime_type = get_file_mime_type(file.filename or "unknown", file_content)

        # Перевіряємо безпеку файлу
        if not is_file_safe(file_content, file.filename or ""):
            raise HTTPException(
                status_code=400,
                detail="File appears to be unsafe or contains malicious content"
            )

        # Генеруємо унікальне ім'я файлу
        prefix = f"{folder}_" if folder else ""
        unique_filename = generate_unique_filename(file.filename or "unknown", prefix)

        # Визначаємо категорію та створюємо шлях
        category = get_file_category(actual_mime_type, file.filename or "")
        file_directory = Path(settings.UPLOAD_DIR) / category
        ensure_dir_exists(str(file_directory))

        file_path = file_directory / unique_filename

        # Зберігаємо файл
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)

        # Обчислюємо хеш файлу
        file_hash = calculate_file_hash(file_content)

        # Обробляємо зображення
        thumbnail_url = None
        optimized_info = {}

        if category == 'images':
            try:
                # Оптимізуємо зображення
                optimization_result = optimize_image(str(file_path))
                if optimization_result:
                    optimized_info = optimization_result

                # Створюємо thumbnail
                thumbnail_path = create_thumbnail(str(file_path))
                if thumbnail_path:
                    thumbnail_filename = Path(thumbnail_path).name
                    thumbnail_url = f"/uploads/{category}/thumbnails/{thumbnail_filename}"

            except Exception as e:
                logger.warning(f"Failed to process image {file_path}: {e}")

        # Формуємо результат
        result = {
            "name": unique_filename,
            "original_name": file.filename or "unknown",
            "path": str(file_path),
            "url": f"/uploads/{category}/{unique_filename}",
            "thumbnail_url": thumbnail_url,
            "category": category,
            "size": file_size,
            "content_type": actual_mime_type,
            "hash": file_hash,
            **optimized_info
        }

        logger.info(f"File saved successfully: {unique_filename} ({file_size} bytes)")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save file {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")


def delete_file(filename: str) -> bool:
    """Видаляє файл з диску."""
    try:
        deleted = False

        # Шукаємо файл у всіх категоріях
        for category in ['images', 'documents', 'media', 'other']:
            file_path = Path(settings.UPLOAD_DIR) / category / filename
            if file_path.exists():
                os.remove(file_path)
                deleted = True
                logger.info(f"Deleted file: {file_path}")

                # Видаляємо thumbnail якщо існує
                if category == 'images':
                    thumbnail_path = file_path.parent / 'thumbnails' / filename
                    if thumbnail_path.exists():
                        os.remove(thumbnail_path)
                        logger.info(f"Deleted thumbnail: {thumbnail_path}")

        return deleted

    except Exception as e:
        logger.error(f"Failed to delete file {filename}: {e}")
        return False


def is_file_safe(content: bytes, filename: str) -> bool:
    """Перевіряє безпеку файлу за змістом."""
    try:
        # Перевіряємо на наявність підозрілих патернів
        suspicious_patterns = [
            b'<script',
            b'javascript:',
            b'vbscript:',
            b'<?php',
            b'<%',
            b'exec(',
            b'system(',
            b'shell_exec'
        ]

        content_lower = content.lower()
        for pattern in suspicious_patterns:
            if pattern in content_lower:
                logger.warning(f"Suspicious pattern found in file {filename}: {pattern}")
                return False

        # Перевіряємо розширення
        if filename:
            ext = Path(filename).suffix.lower()
            dangerous_extensions = [
                '.exe', '.bat', '.cmd', '.com', '.pif', '.scr', '.vbs',
                '.js', '.jar', '.php', '.asp', '.aspx', '.jsp'
            ]
            if ext in dangerous_extensions:
                logger.warning(f"Dangerous file extension: {ext}")
                return False

        return True

    except Exception as e:
        logger.error(f"Error checking file safety: {e}")
        return False


# ============ ОБРОБКА ЗОБРАЖЕНЬ ============

def create_thumbnail(image_path: str, size: tuple = (300, 300)) -> Optional[str]:
    """Створює thumbnail для зображення з покращеною обробкою."""
    try:
        with Image.open(image_path) as img:
            # Автоматично повертаємо зображення відповідно до EXIF
            img = ImageOps.exif_transpose(img)

            # Конвертуємо RGBA в RGB для JPEG
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background

            # Створюємо thumbnail зі збереженням пропорцій
            img.thumbnail(size, Image.Resampling.LANCZOS)

            # Створюємо папку для thumbnails
            thumbnail_dir = Path(image_path).parent / 'thumbnails'
            ensure_dir_exists(str(thumbnail_dir))

            # Зберігаємо thumbnail
            thumbnail_path = thumbnail_dir / Path(image_path).name

            # Визначаємо формат збереження
            save_format = 'JPEG'
            save_kwargs = {'format': save_format, 'optimize': True, 'quality': 85}

            if Path(image_path).suffix.lower() in ['.png']:
                save_format = 'PNG'
                save_kwargs = {'format': save_format, 'optimize': True}

            img.save(thumbnail_path, **save_kwargs)
            logger.info(f"Thumbnail created: {thumbnail_path}")
            return str(thumbnail_path)

    except Exception as e:
        logger.error(f"Failed to create thumbnail for {image_path}: {e}")
        return None


def optimize_image(image_path: str, quality: int = 85, max_width: int = 1920) -> Optional[Dict[str, Any]]:
    """Оптимізує зображення за розміром та якістю."""
    try:
        original_size = os.path.getsize(image_path)

        with Image.open(image_path) as img:
            original_dimensions = img.size

            # Автоматично повертаємо зображення
            img = ImageOps.exif_transpose(img)

            # Змінюємо розмір якщо зображення завелике
            resized = False
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                resized = True

            # Конвертуємо в RGB якщо потрібно для JPEG
            if img.mode in ('RGBA', 'P') and Path(image_path).suffix.lower() in ['.jpg', '.jpeg']:
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img

            # Зберігаємо зі стисканням
            save_kwargs = {'optimize': True}
            if Path(image_path).suffix.lower() in ['.jpg', '.jpeg']:
                save_kwargs['quality'] = quality
                save_kwargs['format'] = 'JPEG'
            elif Path(image_path).suffix.lower() in ['.png']:
                save_kwargs['format'] = 'PNG'

            img.save(image_path, **save_kwargs)

        optimized_size = os.path.getsize(image_path)
        compression_ratio = (original_size - optimized_size) / original_size * 100

        result = {
            "original_size": original_size,
            "optimized_size": optimized_size,
            "compression_ratio": round(compression_ratio, 2),
            "original_dimensions": original_dimensions,
            "final_dimensions": img.size,
            "resized": resized
        }

        logger.info(f"Image optimized: {image_path}, saved {compression_ratio:.1f}%")
        return result

    except Exception as e:
        logger.error(f"Failed to optimize image {image_path}: {e}")
        return None


def get_image_dimensions(image_path: str) -> Optional[tuple]:
    """Отримує розміри зображення."""
    try:
        with Image.open(image_path) as img:
            return img.size
    except Exception as e:
        logger.error(f"Failed to get image dimensions for {image_path}: {e}")
        return None


def create_image_placeholder(width: int, height: int, text: str = "", bg_color: str = "#f0f0f0") -> bytes:
    """Створює placeholder зображення."""
    try:
        img = Image.new('RGB', (width, height), color=bg_color)

        if text:
            draw = ImageDraw.Draw(img)
            # Спрощений підхід до шрифту
            try:
                font = ImageFont.load_default()
            except:
                font = None

            if font:
                # Розраховуємо позицію тексту
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                x = (width - text_width) // 2
                y = (height - text_height) // 2

                draw.text((x, y), text, fill="black", font=font)

        # Конвертуємо в bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        return img_bytes.getvalue()

    except Exception as e:
        logger.error(f"Failed to create image placeholder: {e}")
        return b''


# ============ ТЕКСТОВІ УТИЛІТИ ============

def slugify(text: str) -> str:
    """Створює slug з тексту з підтримкою кирилиці."""
    if not text:
        return ""

    # Нормалізуємо unicode
    text = unicodedata.normalize('NFKD', text)

    # Приводимо до нижнього регістру
    text = text.lower().strip()

    # Транслітерація кирилиці
    cyrillic_translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ye',
        'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'і': 'i', 'ї': 'yi', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
        'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }

    for cyrillic, latin in cyrillic_translit.items():
        text = text.replace(cyrillic, latin)

    # Замінюємо пробіли та спецсимволи на дефіси
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)

    # Видаляємо дефіси на початку та в кінці
    text = text.strip('-')

    # Обмежуємо довжину
    if len(text) > 50:
        text = text[:50].rstrip('-')

    return text or "item"


def sanitize_filename(filename: str) -> str:
    """Очищує ім'я файлу від небезпечних символів."""
    if not filename:
        return "unnamed_file"

    # Видаляємо небезпечні символи
    unsafe_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/', '\x00', '\n', '\r']
    clean_name = filename

    for char in unsafe_chars:
        clean_name = clean_name.replace(char, '_')

    # Замінюємо множинні підкреслення та пробіли
    clean_name = re.sub(r'[_\s]+', '_', clean_name)

    # Обмежуємо довжину
    name, ext = os.path.splitext(clean_name)
    if len(name) > 100:
        name = name[:100]

    # Переконуємося що ім'я не порожнє
    if not name.strip('_'):
        name = "file"

    return f"{name}{ext}".strip('_')


def sanitize_html(content: str, allowed_tags: Optional[List[str]] = None) -> str:
    """Очищає HTML від небезпечних тегів та атрибутів."""
    if not content:
        return ""

    if allowed_tags is None:
        allowed_tags = [
            'p', 'br', 'strong', 'em', 'u', 'ul', 'ol', 'li', 'h1', 'h2', 'h3',
            'h4', 'h5', 'h6', 'a', 'img', 'blockquote', 'code', 'pre'
        ]

    allowed_attributes = {
        'a': ['href', 'title'],
        'img': ['src', 'alt', 'width', 'height'],
        '*': ['class']
    }

    return bleach.clean(
        content,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=True
    )


def extract_text_from_html(html_content: str) -> str:
    """Витягає чистий текст з HTML."""
    if not html_content:
        return ""

    # Видаляємо всі HTML теги
    clean_text = bleach.clean(html_content, tags=[], strip=True)

    # Очищуємо зайві пробіли
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    return clean_text


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Обрізає текст до максимальної довжини."""
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    # Обрізаємо по словах якщо можливо
    truncated = text[:max_length - len(suffix)]
    last_space = truncated.rfind(' ')

    if last_space > max_length * 0.7:  # Якщо останній пробіл не занадто близько до початку
        truncated = truncated[:last_space]

    return truncated + suffix


def validate_email(email: str) -> bool:
    """Валідує email адресу."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email.strip().lower()) is not None


def validate_phone(phone: str) -> bool:
    """Валідує номер телефону."""
    # Видаляємо всі пробіли, дефіси, дужки
    clean_phone = re.sub(r'[\s\-\(\)]+', '', phone)

    # Перевіряємо формат
    pattern = r'^\+?[1-9]\d{7,14}$'
    return re.match(pattern, clean_phone) is not None


def validate_telegram(telegram: str) -> bool:
    """Валідує Telegram username або посилання."""
    telegram = telegram.strip()

    # Формати Telegram
    patterns = [
        r'^@[a-zA-Z0-9_]{5,32}$',  # @username
        r'^https?://(t\.me|telegram\.me)/[a-zA-Z0-9_]{5,32}$',  # посилання
        r'^[a-zA-Z0-9_]{5,32}$'  # username без @
    ]

    return any(re.match(pattern, telegram) for pattern in patterns)


def normalize_phone(phone: str) -> str:
    """Нормалізує номер телефону."""
    clean_phone = re.sub(r'[\s\-\(\)]+', '', phone)

    # Додаємо + якщо немає
    if not clean_phone.startswith('+'):
        if clean_phone.startswith('380'):
            clean_phone = '+' + clean_phone
        elif clean_phone.startswith('0'):
            clean_phone = '+38' + clean_phone

    return clean_phone


def generate_excerpt(text: str, max_length: int = 160) -> str:
    """Генерує анонс з тексту."""
    if not text:
        return ""

    # Видаляємо HTML теги
    clean_text = extract_text_from_html(text)

    # Обрізаємо
    excerpt = truncate_text(clean_text, max_length)

    return excerpt


# ============ РОБОТА З ДАНИМИ ============

def split_features_string(features_string: str) -> List[str]:
    """Розділяє рядок функцій на список."""
    if not features_string or not features_string.strip():
        return []

    # Розділяємо за комами та очищуємо від зайвих пробілів
    features = [feature.strip() for feature in features_string.split(',')]

    # Видаляємо порожні елементи
    return [feature for feature in features if feature]


def join_features_list(features_list: List[str]) -> str:
    """Об'єднує список функцій в рядок."""
    if not features_list:
        return ""

    # Очищуємо від зайвих пробілів та об'єднуємо
    clean_features = [str(feature).strip() for feature in features_list if str(feature).strip()]
    return ', '.join(clean_features)


def get_file_size_human(size_bytes: int) -> str:
    """Конвертує розмір файлу в зручний для читання формат."""
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)

    while size >= 1024 and i < len(size_names) - 1:
        size /= 1024
        i += 1

    return f"{size:.1f} {size_names[i]}"


def parse_json_safe(json_string: str, default: Any = None) -> Any:
    """Безпечно парсить JSON рядок."""
    if not json_string or not json_string.strip():
        return default

    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse JSON: {e}")
        return default


def format_datetime(dt: datetime, format_string: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Форматує дату та час."""
    if not dt:
        return ""

    try:
        return dt.strftime(format_string)
    except Exception as e:
        logger.error(f"Failed to format datetime: {e}")
        return str(dt)


def get_time_ago(dt: datetime) -> str:
    """Повертає час у форматі 'X хвилин тому'."""
    if not dt:
        return ""

    now = datetime.utcnow()
    diff = now - dt

    if diff.days > 0:
        if diff.days == 1:
            return "1 день тому"
        elif diff.days < 30:
            return f"{diff.days} днів тому"
        elif diff.days < 365:
            months = diff.days // 30
            return f"{months} місяць тому" if months == 1 else f"{months} місяців тому"
        else:
            years = diff.days // 365
            return f"{years} рік тому" if years == 1 else f"{years} років тому"

    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours} годин тому" if hours != 1 else "1 годину тому"

    minutes = diff.seconds // 60
    if minutes > 0:
        return f"{minutes} хвилин тому" if minutes != 1 else "1 хвилину тому"

    return "щойно"


# ============ URL ТА БЕЗПЕКА ============

def is_safe_url(url: str, allowed_hosts: Optional[List[str]] = None) -> bool:
    """Перевіряє безпеку URL."""
    if not url:
        return False

    try:
        parsed = urlparse(url)

        # Перевіряємо протокол
        if parsed.scheme not in ['http', 'https', '']:
            return False

        # Якщо вказані дозволені хости
        if allowed_hosts and parsed.netloc:
            if parsed.netloc not in allowed_hosts:
                return False

        # Перевіряємо на небезпечні символи
        dangerous_chars = ['<', '>', '"', '\'']
        if any(char in url for char in dangerous_chars):
            return False

        return True

    except Exception:
        return False


def clean_url(url: str) -> str:
    """Очищує URL від небезпечних символів."""
    if not url:
        return ""

    # Видаляємо небезпечні символи
    url = re.sub(r'[<>"\']', '', url)

    # Переконуємося що URL починається з http/https
    if url and not url.startswith(('http://', 'https://')):
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('/'):
            url = 'https://' + url

    return url


def generate_safe_redirect_url(base_url: str, path: str) -> str:
    """Генерує безпечний URL для редиректу."""
    try:
        return urljoin(base_url, path)
    except Exception:
        return base_url


# ============ СТАТИСТИКА ТА АНАЛІТИКА ============

def get_upload_stats() -> Dict[str, Any]:
    """Отримує статистику завантажених файлів."""
    try:
        stats = {
            "total_files": 0,
            "total_size": 0,
            "categories": {}
        }

        upload_dir = Path(settings.UPLOAD_DIR)
        if not upload_dir.exists():
            return stats

        for category_dir in upload_dir.iterdir():
            if category_dir.is_dir() and category_dir.name != 'thumbnails':
                category_stats = {
                    "count": 0,
                    "size": 0,
                    "types": {}
                }

                for file_path in category_dir.rglob('*'):
                    if file_path.is_file() and file_path.name not in ['.gitkeep', '.DS_Store']:
                        file_size = file_path.stat().st_size
                        file_ext = file_path.suffix.lower()

                        category_stats["count"] += 1
                        category_stats["size"] += file_size
                        stats["total_files"] += 1
                        stats["total_size"] += file_size

                        # Статистика по типах файлів
                        if file_ext in category_stats["types"]:
                            category_stats["types"][file_ext]["count"] += 1
                            category_stats["types"][file_ext]["size"] += file_size
                        else:
                            category_stats["types"][file_ext] = {
                                "count": 1,
                                "size": file_size
                            }

                stats["categories"][category_dir.name] = category_stats

        # Додаємо читабельний розмір
        stats["total_size_human"] = get_file_size_human(stats["total_size"])

        return stats

    except Exception as e:
        logger.error(f"Failed to get upload stats: {e}")
        return {"error": str(e)}


def clean_old_files(directory: str, days_old: int = 30, dry_run: bool = False) -> Dict[str, Any]:
    """Видаляє старі файли з директорії."""
    if days_old <= 0:
        return {"error": "days_old must be positive number"}

    removed_count = 0
    removed_size = 0
    cutoff_time = time.time() - (days_old * 24 * 60 * 60)

    try:
        for file_path in Path(directory).rglob('*'):
            if file_path.is_file() and file_path.name not in ['.gitkeep', '.DS_Store']:
                try:
                    if file_path.stat().st_mtime < cutoff_time:
                        file_size = file_path.stat().st_size

                        if not dry_run:
                            os.remove(file_path)
                            logger.info(f"Removed old file: {file_path}")

                        removed_count += 1
                        removed_size += file_size

                except Exception as e:
                    logger.error(f"Failed to remove {file_path}: {e}")

        result = {
            "removed_count": removed_count,
            "removed_size": removed_size,
            "removed_size_human": get_file_size_human(removed_size),
            "cutoff_days": days_old,
            "dry_run": dry_run
        }

        if dry_run:
            logger.info(f"Dry run: would remove {removed_count} files ({get_file_size_human(removed_size)})")
        else:
            logger.info(f"Cleaned up {removed_count} old files ({get_file_size_human(removed_size)})")

        return result

    except Exception as e:
        logger.error(f"Failed to clean directory {directory}: {e}")
        return {"error": str(e)}


def calculate_storage_usage() -> Dict[str, Any]:
    """Розраховує використання сховища."""
    try:
        upload_dir = Path(settings.UPLOAD_DIR)
        if not upload_dir.exists():
            return {"total_size": 0, "available_space": 0}

        # Розрахунок загального розміру
        total_size = sum(
            f.stat().st_size for f in upload_dir.rglob('*')
            if f.is_file() and f.name not in ['.gitkeep', '.DS_Store']
        )

        # Розрахунок доступного місця
        statvfs = os.statvfs(upload_dir)
        available_space = statvfs.f_frsize * statvfs.f_bavail

        return {
            "total_size": total_size,
            "total_size_human": get_file_size_human(total_size),
            "available_space": available_space,
            "available_space_human": get_file_size_human(available_space),
            "usage_percentage": (total_size / (total_size + available_space)) * 100 if (
                                                                                                   total_size + available_space) > 0 else 0
        }

    except Exception as e:
        logger.error(f"Failed to calculate storage usage: {e}")
        return {"error": str(e)}