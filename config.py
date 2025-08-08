import os
import secrets
from typing import List, Optional, Union, Dict, Any
from pathlib import Path
from dotenv import load_dotenv
import logging

# Завантажуємо змінні з .env файлу
load_dotenv()

logger = logging.getLogger(__name__)


class Settings:
    """Клас налаштувань програми з валідацією та значеннями за замовчуванням."""

    # ============ ОСНОВНІ НАЛАШТУВАННЯ ============
    APP_NAME: str = os.getenv("APP_NAME", "WebCraft Pro API")
    VERSION: str = os.getenv("VERSION", "1.0.0")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes", "on")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Середовище (development, staging, production)
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

    # ============ БАЗА ДАНИХ MYSQL ============
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "")

    # Додаткові параметри БД
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    DB_ECHO: bool = DEBUG  # Логування SQL запитів

    @property
    def DATABASE_URL(self) -> str:
        """Формує URL для підключення до бази даних."""
        if not all([self.DB_HOST, self.DB_USER, self.DB_PASSWORD, self.DB_NAME]):
            raise ValueError("Database configuration is incomplete")

        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    # ============ БЕЗПЕКА JWT ============
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 години
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))  # 30 днів

    # ============ CORS НАЛАШТУВАННЯ ============
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "https://webcraft.pro",
        "https://www.webcraft.pro",
        "https://admin.webcraft.pro",
        # 🆕 ДОБАВЛЯЕМ ПРОДАКШН ДОМЕНЫ ДЛЯ LAUNCHBYTE:
        "https://launchbyte.org",           # ← ОСНОВНОЙ ДОМЕН
        "https://www.launchbyte.org",       # ← WWW версия
        "https://launchbyte-api-production.up.railway.app"  # ← API домен (для самообращений)
    ]

    # Додаткові origins з ENV
    CORS_ORIGINS_ENV: str = os.getenv("CORS_ORIGINS", "")
    if CORS_ORIGINS_ENV:
        additional_origins = [origin.strip() for origin in CORS_ORIGINS_ENV.split(",")]
        ALLOWED_ORIGINS.extend(additional_origins)

    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # ============ ФАЙЛИ ТА ЗАВАНТАЖЕННЯ ============
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(10 * 1024 * 1024)))  # 10MB

    # Дозволені розширення файлів
    ALLOWED_EXTENSIONS: List[str] = [
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",  # Зображення
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv", ".rtf",  # Документи
        ".mp4", ".avi", ".mov", ".webm", ".mp3", ".wav"  # Медіа (за потреби)
    ]

    # Дозволені MIME типи
    ALLOWED_MIME_TYPES: List[str] = [
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain", "text/csv"
    ]

    # Налаштування зображень
    IMAGE_MAX_WIDTH: int = int(os.getenv("IMAGE_MAX_WIDTH", "1920"))
    IMAGE_QUALITY: int = int(os.getenv("IMAGE_QUALITY", "85"))
    THUMBNAIL_SIZE: tuple = (300, 300)

    # ============ EMAIL НАЛАШТУВАННЯ ============
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
    SMTP_USE_SSL: bool = os.getenv("SMTP_USE_SSL", "False").lower() in ("true", "1", "yes")

    # Email адреси
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "noreply@webcraft.pro")
    ADMIN_EMAIL_NOTIFICATIONS: str = os.getenv("ADMIN_EMAIL_NOTIFICATIONS", "admin@webcraft.pro")
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "support@webcraft.pro")

    # Шаблони email
    EMAIL_TEMPLATES_DIR: str = os.getenv("EMAIL_TEMPLATES_DIR", "templates/email")

    # ============ АДМІН КОРИСТУВАЧ ============
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@webcraft.pro")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_NAME: str = os.getenv("ADMIN_NAME", "Administrator")

    # ============ ПАГІНАЦІЯ ============
    DEFAULT_PAGE_SIZE: int = int(os.getenv("DEFAULT_PAGE_SIZE", "20"))
    MAX_PAGE_SIZE: int = int(os.getenv("MAX_PAGE_SIZE", "100"))

    # ============ RATE LIMITING ============
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    RATE_LIMIT_PER_HOUR: int = int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))

    # Спеціальні ліміти для форм
    FORM_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("FORM_RATE_LIMIT_PER_MINUTE", "5"))
    FORM_RATE_LIMIT_PER_HOUR: int = int(os.getenv("FORM_RATE_LIMIT_PER_HOUR", "20"))

    # ============ COOKIE НАЛАШТУВАННЯ ============
    COOKIE_SECURE: bool = not DEBUG and ENVIRONMENT == "production"
    COOKIE_HTTPONLY: bool = True
    COOKIE_SAMESITE: str = "lax"
    COOKIE_MAX_AGE: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # в секундах
    COOKIE_DOMAIN: Optional[str] = os.getenv("COOKIE_DOMAIN")

    # ============ КЕШУВАННЯ (REDIS) ============
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "3600"))  # 1 година

    # ============ ЛОГУВАННЯ ============
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO" if not DEBUG else "DEBUG")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE")
    LOG_MAX_SIZE: int = int(os.getenv("LOG_MAX_SIZE", str(10 * 1024 * 1024)))  # 10MB
    LOG_BACKUP_COUNT: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    # ============ МОНІТОРИНГ ============
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")
    ENABLE_METRICS: bool = os.getenv("ENABLE_METRICS", "True").lower() in ("true", "1", "yes")

    # ============ ЗОВНІШНІ СЕРВІСИ ============
    # Google Analytics
    GOOGLE_ANALYTICS_ID: Optional[str] = os.getenv("GOOGLE_ANALYTICS_ID")

    # reCAPTCHA
    RECAPTCHA_SITE_KEY: Optional[str] = os.getenv("RECAPTCHA_SITE_KEY")
    RECAPTCHA_SECRET_KEY: Optional[str] = os.getenv("RECAPTCHA_SECRET_KEY")
    RECAPTCHA_ENABLED: bool = os.getenv("RECAPTCHA_ENABLED", "False").lower() in ("true", "1", "yes")

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
    TELEGRAM_NOTIFICATIONS: bool = os.getenv("TELEGRAM_NOTIFICATIONS", "False").lower() in ("true", "1", "yes")

    # ============ БЕЗПЕКА ============
    # Trusted proxies (для отримання справжнього IP)
    TRUSTED_PROXIES: List[str] = [
        "127.0.0.1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
    ]

    # Content Security Policy
    CSP_DEFAULT_SRC: List[str] = ["'self'"]
    CSP_SCRIPT_SRC: List[str] = ["'self'", "'unsafe-inline'", "https://www.google.com", "https://www.gstatic.com"]
    CSP_STYLE_SRC: List[str] = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
    CSP_IMG_SRC: List[str] = ["'self'", "data:", "https:"]
    CSP_FONT_SRC: List[str] = ["'self'", "https://fonts.gstatic.com"]

    # ============ FEATURES FLAGS ============
    ENABLE_REGISTRATION: bool = os.getenv("ENABLE_REGISTRATION", "True").lower() in ("true", "1", "yes")
    ENABLE_REVIEWS: bool = os.getenv("ENABLE_REVIEWS", "True").lower() in ("true", "1", "yes")
    ENABLE_FILE_UPLOAD: bool = os.getenv("ENABLE_FILE_UPLOAD", "True").lower() in ("true", "1", "yes")
    MAINTENANCE_MODE: bool = os.getenv("MAINTENANCE_MODE", "False").lower() in ("true", "1", "yes")

    # ============ ЛОКАЛІЗАЦІЯ ============
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "uk")
    SUPPORTED_LANGUAGES: List[str] = ["uk", "en"]

    # ============ МЕТОДИ НАЛАШТУВАНЬ ============

    def configure(self, **kwargs):
        """Налаштовує параметри з переданих аргументів."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.info(f"Configuration updated: {key}")

    def validate_required_settings(self):
        """Перевіряє обов'язкові налаштування."""
        required_settings = {
            'DB_HOST': self.DB_HOST,
            'DB_USER': self.DB_USER,
            'DB_PASSWORD': self.DB_PASSWORD,
            'DB_NAME': self.DB_NAME,
            'SECRET_KEY': self.SECRET_KEY,
            'ADMIN_PASSWORD': self.ADMIN_PASSWORD
        }

        missing = [key for key, value in required_settings.items() if not value]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")

        # Валідація SECRET_KEY
        if len(self.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")

        # Валідація паролю адміна
        if len(self.ADMIN_PASSWORD) < 8:
            raise ValueError("ADMIN_PASSWORD must be at least 8 characters long")

        # Валідація email адміна
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, self.ADMIN_EMAIL):
            raise ValueError("ADMIN_EMAIL must be a valid email address")

        logger.info("All required settings validated successfully")

    def generate_secret_key(self) -> str:
        """Генерує новий SECRET_KEY."""
        return secrets.token_urlsafe(64)

    def is_production(self) -> bool:
        """Перевіряє чи це продакшн середовище."""
        return self.ENVIRONMENT == "production"

    def is_development(self) -> bool:
        """Перевіряє чи це середовище розробки."""
        return self.ENVIRONMENT == "development"

    def get_database_config(self) -> Dict[str, Any]:
        """Повертає конфігурацію бази даних."""
        return {
            "url": self.DATABASE_URL,
            "pool_size": self.DB_POOL_SIZE,
            "max_overflow": self.DB_MAX_OVERFLOW,
            "pool_recycle": self.DB_POOL_RECYCLE,
            "echo": self.DB_ECHO
        }

    def get_cors_config(self) -> Dict[str, Any]:
        """Повертає конфігурацію CORS."""
        return {
            "allow_origins": self.ALLOWED_ORIGINS,
            "allow_credentials": self.CORS_ALLOW_CREDENTIALS,
            "allow_methods": self.CORS_ALLOW_METHODS,
            "allow_headers": self.CORS_ALLOW_HEADERS
        }

    def get_email_config(self) -> Dict[str, Any]:
        """Повертає конфігурацію email."""
        return {
            "smtp_server": self.SMTP_SERVER,
            "smtp_port": self.SMTP_PORT,
            "username": self.SMTP_USERNAME,
            "password": self.SMTP_PASSWORD,
            "use_tls": self.SMTP_USE_TLS,
            "use_ssl": self.SMTP_USE_SSL,
            "from_email": self.FROM_EMAIL
        }

    def get_security_headers(self) -> Dict[str, str]:
        """Повертає заголовки безпеки."""
        csp_policy = "; ".join([
            f"default-src {' '.join(self.CSP_DEFAULT_SRC)}",
            f"script-src {' '.join(self.CSP_SCRIPT_SRC)}",
            f"style-src {' '.join(self.CSP_STYLE_SRC)}",
            f"img-src {' '.join(self.CSP_IMG_SRC)}",
            f"font-src {' '.join(self.CSP_FONT_SRC)}"
        ])

        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": csp_policy
        }

        if self.is_production():
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return headers

    def get_file_upload_config(self) -> Dict[str, Any]:
        """Повертає конфігурацію завантаження файлів."""
        return {
            "upload_dir": self.UPLOAD_DIR,
            "max_file_size": self.MAX_FILE_SIZE,
            "allowed_extensions": self.ALLOWED_EXTENSIONS,
            "allowed_mime_types": self.ALLOWED_MIME_TYPES,
            "image_max_width": self.IMAGE_MAX_WIDTH,
            "image_quality": self.IMAGE_QUALITY,
            "thumbnail_size": self.THUMBNAIL_SIZE
        }

    def get_public_config(self) -> Dict[str, Any]:
        """Повертає публічну конфігурацію для фронтенду."""
        return {
            "app_name": self.APP_NAME,
            "version": self.VERSION,
            "debug": self.DEBUG,
            "environment": self.ENVIRONMENT,
            "max_file_size": self.MAX_FILE_SIZE,
            "allowed_extensions": self.ALLOWED_EXTENSIONS,
            "default_language": self.DEFAULT_LANGUAGE,
            "supported_languages": self.SUPPORTED_LANGUAGES,
            "enable_registration": self.ENABLE_REGISTRATION,
            "enable_reviews": self.ENABLE_REVIEWS,
            "maintenance_mode": self.MAINTENANCE_MODE,
            "google_analytics_id": self.GOOGLE_ANALYTICS_ID,
            "recaptcha_site_key": self.RECAPTCHA_SITE_KEY if self.RECAPTCHA_ENABLED else None
        }

    def validate_email_config(self) -> bool:
        """Валідує конфігурацію email."""
        required_fields = [
            self.SMTP_SERVER,
            self.SMTP_USERNAME,
            self.SMTP_PASSWORD,
            self.FROM_EMAIL
        ]

        if not all(required_fields):
            logger.warning("Email configuration is incomplete")
            return False

        # Додаткова валідація email адрес
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

        emails_to_check = [self.FROM_EMAIL, self.ADMIN_EMAIL_NOTIFICATIONS, self.SUPPORT_EMAIL]
        for email in emails_to_check:
            if email and not re.match(email_pattern, email):
                logger.warning(f"Invalid email address: {email}")
                return False

        return True

    def setup_logging(self):
        """Налаштовує систему логування."""
        import logging.config

        log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S"
                },
                "detailed": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": self.LOG_LEVEL,
                    "formatter": "default" if not self.DEBUG else "detailed",
                    "stream": "ext://sys.stdout"
                }
            },
            "loggers": {
                "": {
                    "level": self.LOG_LEVEL,
                    "handlers": ["console"],
                    "propagate": False
                },
                "sqlalchemy.engine": {
                    "level": "INFO" if self.DB_ECHO else "WARNING",
                    "handlers": ["console"],
                    "propagate": False
                },
                "uvicorn": {
                    "level": "INFO",
                    "handlers": ["console"],
                    "propagate": False
                }
            }
        }

        # Додаємо файловий handler якщо вказано
        if self.LOG_FILE:
            log_config["handlers"]["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "level": self.LOG_LEVEL,
                "formatter": "detailed",
                "filename": self.LOG_FILE,
                "maxBytes": self.LOG_MAX_SIZE,
                "backupCount": self.LOG_BACKUP_COUNT
            }

            # Додаємо file handler до всіх loggers
            for logger_config in log_config["loggers"].values():
                if "file" not in logger_config["handlers"]:
                    logger_config["handlers"].append("file")

        logging.config.dictConfig(log_config)
        logger.info(f"Logging configured with level: {self.LOG_LEVEL}")


# ============ СТВОРЕННЯ ТА ІНІЦІАЛІЗАЦІЯ НАЛАШТУВАНЬ ============

def create_settings() -> Settings:
    """Створює та валідує налаштування."""
    settings = Settings()

    # Автоматично генеруємо SECRET_KEY якщо він не встановлений
    if not settings.SECRET_KEY:
        settings.SECRET_KEY = settings.generate_secret_key()
        logger.warning("SECRET_KEY was generated automatically. Please set it in environment variables for production!")

    return settings


# Створення глобального екземпляру налаштувань
settings = create_settings()


def ensure_upload_dir():
    """Створення папок для завантажень."""
    upload_path = Path(settings.UPLOAD_DIR)
    upload_path.mkdir(exist_ok=True)

    # Створення підпапок
    categories = ["images", "documents", "media", "other"]
    for category in categories:
        category_path = upload_path / category
        category_path.mkdir(exist_ok=True)

        # Створюємо папку thumbnails для зображень
        if category == "images":
            thumbnails_path = category_path / "thumbnails"
            thumbnails_path.mkdir(exist_ok=True)

    logger.info(f"Upload directories created at: {upload_path.absolute()}")
    return upload_path


def validate_environment():
    """Валідує середовище та налаштування."""
    try:
        # Валідуємо обов'язкові налаштування
        settings.validate_required_settings()

        # Валідуємо email конфігурацію якщо email функції увімкнені
        if settings.SMTP_SERVER:
            settings.validate_email_config()

        # Створюємо директорії
        ensure_upload_dir()

        # Налаштовуємо логування
        settings.setup_logging()

        logger.info("Environment validation completed successfully")
        logger.info(f"Running in {settings.ENVIRONMENT} environment")

        return True

    except Exception as e:
        logger.error(f"Environment validation failed: {e}")
        raise


# Ініціалізація при імпорті
if __name__ != "__main__":
    try:
        validate_environment()
    except Exception as e:
        print(f"Failed to initialize settings: {e}")
        raise