#!/usr/bin/env python3
"""
WebCraft Pro API - Главный модуль приложения
Профессиональный backend для сайта веб-студии с полным функционалом
Версия: 2.0 с поддержкой управления командой и страницей "О нас"
"""

import sys
import time
import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
import uvicorn

# Добавляем текущую директорию к sys.path
sys.path.append(str(Path(__file__).parent))

try:
    from config import settings
    from database import (
        init_database, check_database_connection,
        get_database_stats, db_manager, backup_database,
        cleanup_old_data
    )
    from routes import router
    from email_service import email_service, validate_email_templates
    from utils import get_upload_stats, calculate_storage_usage, clean_old_files
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("💡 Make sure all required modules are properly installed and configured")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Middleware для улучшенной безопасности."""

    async def dispatch(self, request: Request, call_next):
        # Добавляем уникальный ID запроса
        request_id = f"req_{int(time.time() * 1000000) % 1000000:06d}"
        request.state.request_id = request_id

        # Получаем IP клиента
        client_ip = self.get_client_ip(request)
        request.state.client_ip = client_ip

        # Логируем начало запроса
        start_time = time.time()
        logger.info(f"[{request_id}] {request.method} {request.url.path} from {client_ip}")

        try:
            # Проверяем режим обслуживания
            if getattr(settings, 'MAINTENANCE_MODE', False) and request.url.path not in [
                "/health", "/api/v1/health", "/docs", "/openapi.json"
            ]:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "Service Unavailable",
                        "message": "The service is temporarily unavailable due to maintenance",
                        "retry_after": 3600  # 1 час
                    }
                )

            # Проверяем заблокированные IP (если есть)
            if hasattr(settings, 'BLOCKED_IPS') and client_ip in settings.BLOCKED_IPS:
                logger.warning(f"[{request_id}] Blocked IP attempted access: {client_ip}")
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "Access Forbidden",
                        "message": "Your IP address is blocked"
                    }
                )

            response = await call_next(request)

            # Добавляем заголовки безопасности
            security_headers = {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
                "X-Request-ID": request_id,
                "X-API-Version": settings.VERSION,
                "X-Powered-By": "WebCraft Pro API"
            }

            # Добавляем CSP только для HTML страниц
            if response.headers.get("content-type", "").startswith("text/html"):
                security_headers["Content-Security-Policy"] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: https:; "
                    "font-src 'self' https:; "
                    "connect-src 'self'"
                )

            for header, value in security_headers.items():
                response.headers[header] = value

            # Логируем завершение запроса
            process_time = time.time() - start_time
            logger.info(f"[{request_id}] Response: {response.status_code} in {process_time:.4f}s")

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"[{request_id}] Error: {str(e)} in {process_time:.4f}s")

            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                    "request_id": request_id
                }
            )

    def get_client_ip(self, request: Request) -> str:
        """Получает настоящий IP клиента."""
        # Проверяем заголовки от прокси серверов
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        cloudflare_ip = request.headers.get("CF-Connecting-IP")
        if cloudflare_ip:
            return cloudflare_ip

        return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware для ограничения частоты запросов."""

    def __init__(self, app, calls: int = 60, period: int = 60, exclude_paths: Optional[list] = None):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.clients = {}
        self.exclude_paths = exclude_paths or ["/health", "/metrics", "/favicon.ico"]

    async def dispatch(self, request: Request, call_next):
        # Пропускаем определенные пути
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        client_ip = getattr(request.state, 'client_ip', 'unknown')
        current_time = time.time()

        # Очищаем старые записи каждую минуту
        if current_time % 60 < 1:
            self.cleanup_old_entries(current_time)

        # Проверяем лимит
        if client_ip in self.clients:
            requests = self.clients[client_ip]
            recent_requests = [req_time for req_time in requests if current_time - req_time < self.period]

            if len(recent_requests) >= self.calls:
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return JSONResponse(
                    status_code=HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "Too Many Requests",
                        "message": f"Rate limit exceeded: {self.calls} requests per {self.period} seconds",
                        "retry_after": self.period
                    },
                    headers={"Retry-After": str(self.period)}
                )

            self.clients[client_ip] = recent_requests + [current_time]
        else:
            self.clients[client_ip] = [current_time]

        return await call_next(request)

    def cleanup_old_entries(self, current_time: float):
        """Очищает старые записи для экономии памяти."""
        for client_ip in list(self.clients.keys()):
            requests = self.clients[client_ip]
            recent_requests = [req_time for req_time in requests if current_time - req_time < self.period * 2]

            if recent_requests:
                self.clients[client_ip] = recent_requests
            else:
                del self.clients[client_ip]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events для FastAPI приложения."""
    # Startup
    logger.info("🚀 Starting WebCraft Pro API v2.0...")
    logger.info(f"🔧 Environment: {settings.ENVIRONMENT}")
    logger.info(f"🗄️  Database: {settings.DB_NAME} on {settings.DB_HOST}")
    logger.info(f"👤 Admin: {getattr(settings, 'ADMIN_EMAIL', 'Not configured')}")

    startup_errors = []

    try:
        # Проверяем конфигурацию
        logger.info("🔍 Validating environment configuration...")
        # validate_environment() # Если есть такая функция

        # Инициализируем базу данных
        logger.info("📊 Initializing database...")
        init_database()

        # Проверяем подключение к БД
        if not check_database_connection():
            startup_errors.append("Database connection failed")
        else:
            logger.info("✅ Database connection established")

        # Тестируем email сервис если настроен
        logger.info("📧 Testing email service...")
        if hasattr(settings, 'SMTP_SERVER') and settings.SMTP_SERVER:
            try:
                email_connection_ok = await email_service.test_email_connection()
                if email_connection_ok:
                    logger.info("✅ Email service connected")
                else:
                    logger.warning("⚠️ Email service connection failed")
                    startup_errors.append("Email service not working")
            except Exception as e:
                logger.warning(f"⚠️ Email service error: {e}")
        else:
            logger.info("ℹ️  Email service not configured")

        # Валидируем email шаблоны
        logger.info("📝 Validating email templates...")
        template_validation = validate_email_templates()
        invalid_templates = [name for name, result in template_validation.items() if not result['valid']]
        if invalid_templates:
            logger.warning(f"⚠️ Invalid email templates: {invalid_templates}")

        # Проверяем директории для файлов
        logger.info("📁 Checking upload directories...")
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)

        for category in ['images', 'documents', 'media', 'other']:
            category_dir = upload_dir / category
            category_dir.mkdir(exist_ok=True)
            (category_dir / 'thumbnails').mkdir(exist_ok=True)

        # Статистика базы данных
        logger.info("📈 Gathering database statistics...")
        db_stats = get_database_stats()
        logger.info(f"📊 Database stats: {db_stats.get('users', 0)} users, "
                    f"{db_stats.get('designs', 0)} designs, "
                    f"{db_stats.get('team_members', 0)} team members, "
                    f"{db_stats.get('about_content', 0)} about content entries")

        # Статистика файлов
        upload_stats = get_upload_stats()
        logger.info(f"📁 Upload stats: {upload_stats.get('total_files', 0)} files, "
                    f"{upload_stats.get('total_size_human', '0 B')}")

        # Запускаем фоновые задачи
        logger.info("⚙️  Starting background tasks...")
        asyncio.create_task(background_cleanup_task())

        if startup_errors:
            logger.warning(f"⚠️ Application started with warnings: {startup_errors}")
        else:
            logger.info("✅ Application started successfully!")

        logger.info(f"🌐 Server available at: http://{settings.HOST}:{settings.PORT}")
        if settings.DEBUG:
            logger.info(f"📚 API Documentation: http://{settings.HOST}:{settings.PORT}/docs")
            logger.info(f"📋 ReDoc: http://{settings.HOST}:{settings.PORT}/redoc")

    except Exception as e:
        logger.error(f"❌ Failed to initialize application: {e}")
        import traceback
        traceback.print_exc()
        raise

    yield

    # Shutdown
    logger.info("👋 Application shutting down...")

    # Создаем финальный бэкап если настроено
    if getattr(settings, 'AUTO_BACKUP_ON_SHUTDOWN', False):
        logger.info("💾 Creating shutdown backup...")
        try:
            backup_file = backup_database()
            if backup_file:
                logger.info(f"✅ Shutdown backup created: {backup_file}")
        except Exception as e:
            logger.error(f"❌ Failed to create shutdown backup: {e}")

    logger.info("✅ Application shutdown complete")


async def background_cleanup_task():
    """Фоновая задача для очистки и обслуживания."""
    while True:
        try:
            # Ждем 1 час
            await asyncio.sleep(3600)

            logger.info("🧹 Running background cleanup...")

            # Очищаем старые логи email
            cleanup_result = cleanup_old_data(days_old=30)
            if cleanup_result.get('deleted_email_logs', 0) > 0:
                logger.info(f"🗑️  Cleaned up {cleanup_result['deleted_email_logs']} old email logs")

            # Очищаем старые временные файлы
            temp_cleanup = clean_old_files(
                str(Path(settings.UPLOAD_DIR) / 'temp'),
                days_old=1,
                dry_run=False
            )
            if temp_cleanup.get('removed_count', 0) > 0:
                logger.info(f"🗑️  Cleaned up {temp_cleanup['removed_count']} old temp files")

        except Exception as e:
            logger.error(f"❌ Background cleanup error: {e}")


# Создаем FastAPI приложение
app = FastAPI(
    title="WebCraft Pro API",
    description="""
    🎨 **WebCraft Pro API v2.0** - Профессиональный backend для сайта веб-студии

    ## 🆕 Новые функции в v2.0:
    - 👥 **Управление командой** - полный CRUD для членов команды
    - 📄 **Страница "О нас"** - редактирование контента и миссии
    - 🔐 **Смена пароля** - безопасное изменение паролей администраторов
    - 📧 **Улучшенные уведомления** - расширенные email шаблоны
    - 🛡️ **Усиленная безопасность** - улучшенная система аутентификации

    ## 📋 Основные функции:
    - 🔐 JWT авторизация с cookie поддержкой
    - 🎨 Управление портфолио дизайнов и категорий
    - 💼 Пакеты услуг с детальным описанием
    - ⭐ Система отзывов с модерацией
    - 📋 Обработка заявок на расчет и консультации
    - 📁 Загрузка и оптимизация файлов
    - 🌐 Мультиязычность (UK/EN)
    - 📊 Админ панель со статистикой
    - 📧 Email уведомления
    - 👥 Управление командой и контентом

    ## 🛡️ Безопасность:
    - Rate limiting с исключениями
    - CORS защита с гибкой настройкой
    - Расширенная валидация данных
    - SQL injection защита
    - XSS и CSRF защита
    - Мониторинг подозрительной активности
    - Блокировка IP адресов
    - Режим технического обслуживания

    ## 📊 Мониторинг:
    - Health checks с детальной диагностикой
    - Metrics для мониторинга производительности
    - Логирование всех операций
    - Статистика использования API
    - Автоматическая очистка старых данных

    ## 🚀 API Endpoints:
    - **Аутентификация**: `/api/v1/auth/*`
    - **Дизайны**: `/api/v1/designs/*`
    - **Команда**: `/api/v1/team/*` 🆕
    - **О нас**: `/api/v1/content/about` 🆕
    - **Пакеты**: `/api/v1/packages/*`
    - **Отзывы**: `/api/v1/reviews/*`
    - **Заявки**: `/api/v1/applications/*`
    - **Контент**: `/api/v1/content/*`
    - **Файлы**: `/api/v1/upload`, `/api/v1/files/*`
    - **Админ**: `/api/v1/admin/*`
    """,
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
    contact={
        "name": "WebCraft Pro Support",
        "url": "https://webcraft.pro/contact",
        "email": getattr(settings, 'SUPPORT_EMAIL', 'support@webcraft.pro')
    },
    license_info={
        "name": "Proprietary",
        "url": "https://webcraft.pro/license"
    }
)

# ============ MIDDLEWARE ============

# Добавляем security middleware
app.add_middleware(SecurityMiddleware)

# Rate limiting (только в продакшн)
if settings.ENVIRONMENT == "production":
    app.add_middleware(
        RateLimitMiddleware,
        calls=getattr(settings, 'RATE_LIMIT_PER_MINUTE', 60),
        period=60,
        exclude_paths=["/health", "/metrics", "/favicon.ico", "/docs", "/openapi.json"]
    )

# Gzip сжатие
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Trusted hosts (в продакшн)
if settings.ENVIRONMENT == "production":
    trusted_hosts = getattr(settings, 'TRUSTED_HOSTS', ["webcraft.pro", "*.webcraft.pro"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

# 🔧 CORS MIDDLEWARE - ИСПРАВЛЕНО ДЛЯ LAUNCHBYTE.ORG
logger.info(f"🌐 Configuring CORS for origins: {settings.ALLOWED_ORIGINS}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # ← ИСПОЛЬЗУЕТ НАСТРОЙКИ ИЗ CONFIG.PY
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-Request-ID",
        "Cache-Control"
    ],
    expose_headers=["X-Request-ID", "X-API-Version"],
    max_age=600  # Кэшируем preflight запросы на 10 минут
)


# ============ ОБРАБОТЧИКИ ОШИБОК ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Обработчик HTTP ошибок."""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.warning(f"HTTP {exc.status_code}: {exc.detail} - {request.url} [{request_id}]")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": f"HTTP {exc.status_code}",
            "message": exc.detail,
            "path": str(request.url.path),
            "timestamp": int(time.time()),
            "request_id": request_id
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Обработчик ошибок валидации."""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.warning(f"Validation error: {exc.errors()} - {request.url} [{request_id}]")

    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "message": "Invalid request data",
            "details": exc.errors(),
            "path": str(request.url.path),
            "request_id": request_id
        }
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_exception_handler(request: Request, exc: StarletteHTTPException):
    """Обработчик Starlette HTTP ошибок."""
    request_id = getattr(request.state, 'request_id', 'unknown')

    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "message": "The requested resource was not found",
                "path": str(request.url.path),
                "request_id": request_id
            }
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": f"HTTP {exc.status_code}",
            "message": exc.detail if hasattr(exc, 'detail') else "An error occurred",
            "request_id": request_id
        }
    )


@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc):
    """Обработчик внутренних ошибок сервера."""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.error(f"Internal server error [{request_id}]: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred" if settings.ENVIRONMENT == "production" else str(exc),
            "request_id": request_id,
            "timestamp": int(time.time())
        }
    )


# ============ СТАТИЧЕСКИЕ ФАЙЛЫ ============

# Монтируем статические файлы для загруженных изображений
try:
    upload_path = Path(settings.UPLOAD_DIR)
    if upload_path.exists():
        app.mount("/uploads", StaticFiles(directory=str(upload_path)), name="uploads")
        logger.info(f"Static files mounted: /uploads -> {upload_path}")
    else:
        logger.warning(f"Upload directory not found: {upload_path}")
except Exception as e:
    logger.warning(f"Failed to mount static files: {e}")


# ============ ОСНОВНЫЕ РОУТЫ ============

@app.get("/", tags=["Root"])
async def root():
    """Главная страница API с информацией о сервисе."""
    db_status = "connected" if check_database_connection() else "disconnected"

    # Получаем расширенную статистику
    db_stats = get_database_stats() if db_status == "connected" else {}
    upload_stats = get_upload_stats()
    storage_usage = calculate_storage_usage()

    return {
        "service": "🎨 WebCraft Pro API",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": {
            "status": db_status,
            "stats": {
                "users": db_stats.get('users', 0),
                "designs": db_stats.get('designs', 0),
                "team_members": db_stats.get('team_members', 0),  # Новая статистика
                "about_content": db_stats.get('about_content', 0),  # Новая статистика
                "packages": db_stats.get('packages', 0),
                "reviews": db_stats.get('reviews', 0),
                "applications": db_stats.get('quote_applications', 0) + db_stats.get('consultation_applications', 0)
            }
        },
        "storage": {
            "total_files": upload_stats.get('total_files', 0),
            "total_size": upload_stats.get('total_size_human', '0 B'),
            "usage_percentage": storage_usage.get('usage_percentage', 0)
        },
        "cors": {
            "allowed_origins": settings.ALLOWED_ORIGINS,
            "status": "configured"
        },
        "features": {
            "authentication": "JWT with cookies",
            "database": "MySQL with migrations",
            "file_upload": "Images with optimization",
            "email": "SMTP notifications",
            "localization": "Ukrainian/English",
            "admin_panel": "Full CRUD operations",
            "team_management": "Team members CRUD",  # Новая функция
            "about_page": "About page content management",  # Новая функция
            "password_change": "Secure password updates",  # Новая функция
            "rate_limiting": f"{getattr(settings, 'RATE_LIMIT_PER_MINUTE', 60)} requests/minute",
            "security": "CORS, XSS, CSRF protection"
        },
        "documentation": "/docs" if settings.DEBUG else "Available in development mode",
        "timestamp": int(time.time())
    }


@app.get("/health", tags=["System"])
async def health_check():
    """Детальная проверка состояния системы."""
    checks = {}
    overall_status = "healthy"

    # Проверяем базу данных
    try:
        db_connected = check_database_connection()
        checks["database"] = {
            "status": "ok" if db_connected else "error",
            "details": db_manager.get_connection_info() if db_connected else "Connection failed"
        }
        if not db_connected:
            overall_status = "unhealthy"
    except Exception as e:
        checks["database"] = {"status": "error", "details": str(e)}
        overall_status = "unhealthy"

    # Проверяем email сервис
    try:
        if hasattr(settings, 'SMTP_SERVER') and settings.SMTP_SERVER:
            email_test = await email_service.test_email_connection()
            checks["email"] = {
                "status": "ok" if email_test else "error",
                "details": "SMTP connection successful" if email_test else "SMTP connection failed"
            }
        else:
            checks["email"] = {"status": "not_configured", "details": "SMTP settings missing"}
    except Exception as e:
        checks["email"] = {"status": "error", "details": str(e)}

    # Проверяем файловую систему
    try:
        upload_path = Path(settings.UPLOAD_DIR)
        if upload_path.exists() and upload_path.is_dir():
            # Проверяем доступность записи
            test_file = upload_path / '.write_test'
            try:
                test_file.write_text('test')
                test_file.unlink()
                checks["file_system"] = {
                    "status": "ok",
                    "details": f"Upload directory writable: {upload_path}"
                }
            except Exception:
                checks["file_system"] = {
                    "status": "error",
                    "details": f"Upload directory not writable: {upload_path}"
                }
                overall_status = "degraded"
        else:
            checks["file_system"] = {"status": "error", "details": "Upload directory not found"}
            overall_status = "degraded"
    except Exception as e:
        checks["file_system"] = {"status": "error", "details": str(e)}

    # Проверяем новые таблицы
    try:
        if db_connected:
            db_stats = get_database_stats()
            new_features_ok = (
                    'team_members' in db_stats and
                    'about_content' in db_stats
            )
            checks["new_features"] = {
                "status": "ok" if new_features_ok else "error",
                "details": {
                    "team_members_table": 'team_members' in db_stats,
                    "about_content_table": 'about_content' in db_stats,
                    "team_members_count": db_stats.get('team_members', 0),
                    "about_content_count": db_stats.get('about_content', 0)
                }
            }
    except Exception as e:
        checks["new_features"] = {"status": "error", "details": str(e)}

    # 🆕 CORS проверка
    checks["cors"] = {
        "status": "ok",
        "details": {
            "allowed_origins": len(settings.ALLOWED_ORIGINS),
            "launchbyte_configured": "https://launchbyte.org" in settings.ALLOWED_ORIGINS
        }
    }

    return {
        "status": overall_status,
        "timestamp": int(time.time()),
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "uptime_seconds": int(time.time() - getattr(health_check, '_start_time', time.time())),
        "checks": checks
    }


# Сохраняем время запуска для uptime
health_check._start_time = time.time()


@app.get("/metrics", tags=["System"])
async def get_metrics():
    """Метрики для мониторинга (Prometheus format)."""
    if not getattr(settings, 'ENABLE_METRICS', False):
        raise HTTPException(status_code=404, detail="Metrics disabled")

    try:
        db_stats = get_database_stats()
        upload_stats = get_upload_stats()
        storage_stats = calculate_storage_usage()

        metrics = []

        # Database metrics
        for key, value in db_stats.items():
            if isinstance(value, (int, float)) and key != "error":
                metrics.append(f'webcraft_db_{key} {value}')

        # File metrics
        metrics.extend([
            f'webcraft_files_total {upload_stats.get("total_files", 0)}',
            f'webcraft_files_size_bytes {upload_stats.get("total_size", 0)}',
            f'webcraft_storage_usage_percentage {storage_stats.get("usage_percentage", 0)}'
        ])

        # Application metrics
        metrics.extend([
            f'webcraft_app_version{{version="{settings.VERSION}"}} 1',
            f'webcraft_app_debug{{debug="{settings.DEBUG}"}} {int(settings.DEBUG)}',
            f'webcraft_app_environment{{environment="{settings.ENVIRONMENT}"}} 1',
            f'webcraft_app_uptime_seconds {int(time.time() - getattr(health_check, "_start_time", time.time()))}'
        ])

        # Новые метрики для команды и контента "О нас"
        metrics.extend([
            f'webcraft_team_members_total {db_stats.get("team_members", 0)}',
            f'webcraft_team_members_active {db_stats.get("active_team_members", 0)}',
            f'webcraft_about_content_entries {db_stats.get("about_content", 0)}'
        ])

        # CORS метрики
        metrics.extend([
            f'webcraft_cors_origins_total {len(settings.ALLOWED_ORIGINS)}',
            f'webcraft_cors_launchbyte_configured {int("https://launchbyte.org" in settings.ALLOWED_ORIGINS)}'
        ])

        return Response(
            content="\n".join(metrics) + "\n",
            media_type="text/plain"
        )

    except Exception as e:
        logger.error(f"Failed to generate metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate metrics")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Favicon для API."""
    # Попробуем найти favicon в статических файлах
    favicon_path = Path(settings.UPLOAD_DIR) / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)

    # Возвращаем пустой ответ
    return Response(content="", media_type="image/x-icon")


# ============ API РОУТЫ ============

# Подключаем все API роуты
app.include_router(router, prefix="/api/v1", tags=["API v1"])


# ============ ДОПОЛНИТЕЛЬНЫЕ РОУТЫ ============

@app.get("/api/v1/info", tags=["System"])
async def get_api_info():
    """Информация о API."""
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "database": {
            "type": "MySQL",
            "name": settings.DB_NAME,
            "host": settings.DB_HOST,
            "charset": "utf8mb4"
        },
        "cors": {
            "allowed_origins": settings.ALLOWED_ORIGINS,
            "allow_credentials": settings.CORS_ALLOW_CREDENTIALS,
            "launchbyte_support": "https://launchbyte.org" in settings.ALLOWED_ORIGINS
        },
        "features": {
            "authentication": True,
            "file_upload": True,
            "email_notifications": hasattr(settings, 'SMTP_SERVER') and bool(settings.SMTP_SERVER),
            "rate_limiting": True,
            "cors": True,
            "team_management": True,  # Новая функция
            "about_page_management": True,  # Новая функция
            "password_change": True,  # Новая функция
            "security_monitoring": True,
            "auto_backup": getattr(settings, 'AUTO_BACKUP_ENABLED', False)
        },
        "limits": {
            "max_file_size": settings.MAX_FILE_SIZE,
            "max_file_size_human": f"{settings.MAX_FILE_SIZE // (1024 * 1024)}MB",
            "rate_limit_per_minute": getattr(settings, 'RATE_LIMIT_PER_MINUTE', 60),
            "max_page_size": getattr(settings, 'MAX_PAGE_SIZE', 100),
            "allowed_extensions": getattr(settings, 'ALLOWED_EXTENSIONS', [])
        },
        "new_features": {
            "team_management": "Full CRUD operations for team members",
            "about_page": "Content management for About Us page",
            "password_security": "Enhanced password change with notifications",
            "improved_email": "Extended email templates and notifications",
            "enhanced_security": "Improved security middleware and monitoring"
        }
    }


@app.post("/api/v1/test-email", tags=["System"])
async def test_email_endpoint():
    """Тестовый endpoint для проверки email сервиса (только в debug режиме)."""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")

    if not hasattr(settings, 'SMTP_SERVER') or not settings.SMTP_SERVER:
        raise HTTPException(status_code=503, detail="Email service not configured")

    try:
        # Тестируем подключение
        success = await email_service.test_email_connection()

        # Получаем статистику email
        email_stats = email_service.get_email_stats()

        # Проверяем шаблоны
        template_validation = validate_email_templates()

        return {
            "status": "success" if success else "failed",
            "message": "Email connection test completed",
            "connection_test": success,
            "configuration": {
                "smtp_server": settings.SMTP_SERVER,
                "smtp_port": getattr(settings, 'SMTP_PORT', 587),
                "use_tls": getattr(settings, 'SMTP_USE_TLS', True),
                "from_email": getattr(settings, 'FROM_EMAIL', '')
            },
            "statistics": email_stats,
            "templates": {
                "total": len(email_service.templates),
                "valid": sum(1 for result in template_validation.values() if result['valid']),
                "invalid": sum(1 for result in template_validation.values() if not result['valid'])
            }
        }
    except Exception as e:
        logger.error(f"Email test error: {e}")
        raise HTTPException(status_code=500, detail=f"Email test failed: {str(e)}")


@app.get("/api/v1/backup", tags=["System"])
async def create_backup_endpoint():
    """Создание резервной копии базы данных (только для админов)."""
    # TODO: Добавить проверку админских прав
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        backup_file = backup_database()
        if backup_file:
            return {
                "status": "success",
                "message": "Backup created successfully",
                "backup_file": backup_file,
                "timestamp": int(time.time())
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create backup")
    except Exception as e:
        logger.error(f"Backup creation error: {e}")
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


# ============ ЗАПУСК ПРИЛОЖЕНИЯ ============

if __name__ == "__main__":
    # Конфигурация для запуска
    uvicorn_config = {
        "app": "main:app",
        "host": settings.HOST,
        "port": settings.PORT,
        "reload": settings.DEBUG,
        "log_level": "info",
        "access_log": True,
        "use_colors": True,
        "server_header": False,  # Убираем заголовок сервера для безопасности
        "date_header": True
    }

    # Дополнительные настройки для продакшн
    if settings.ENVIRONMENT == "production":
        uvicorn_config.update({
            "workers": getattr(settings, 'WORKERS', 4),
            "reload": False,
            "access_log": getattr(settings, 'ACCESS_LOG', True)
        })

    # SSL настройки если есть
    if hasattr(settings, 'SSL_KEYFILE') and hasattr(settings, 'SSL_CERTFILE'):
        uvicorn_config.update({
            "ssl_keyfile": settings.SSL_KEYFILE,
            "ssl_certfile": settings.SSL_CERTFILE
        })

    logger.info(f"🚀 Starting server with config: {uvicorn_config}")

    try:
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        logger.info("👋 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        sys.exit(1)