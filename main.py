#!/usr/bin/env python3
"""
WebCraft Pro API - Главный модуль додатку
Професійний backend для сайту веб-студії з повним функціоналом
"""

import sys
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

# Додаємо поточну директорію до sys.path
sys.path.append(str(Path(__file__).parent))

from config import settings, validate_environment
from database import (
    init_database, check_database_connection,
    get_database_stats, db_manager
)
from routes import router
from email_service import email_service

# Налаштування логування
logger = logging.getLogger(__name__)


class CustomMiddleware(BaseHTTPMiddleware):
    """Кастомний middleware для обробки запитів."""

    async def dispatch(self, request: Request, call_next):
        # Додаємо унікальний ID запиту
        request_id = f"req_{int(time.time() * 1000000) % 1000000:06d}"
        request.state.request_id = request_id

        # Логуємо початок запиту
        start_time = time.time()
        client_ip = self.get_client_ip(request)

        logger.info(f"[{request_id}] {request.method} {request.url.path} from {client_ip}")

        try:
            # Перевіряємо режим обслуговування
            if settings.MAINTENANCE_MODE and request.url.path not in ["/health", "/api/v1/health"]:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "Service Unavailable",
                        "message": "The service is temporarily unavailable due to maintenance"
                    }
                )

            response = await call_next(request)

            # Додаємо заголовки безпеки
            security_headers = settings.get_security_headers()
            for header, value in security_headers.items():
                response.headers[header] = value

            # Додаємо кастомні заголовки
            response.headers["X-Request-ID"] = request_id
            response.headers["X-API-Version"] = settings.VERSION

            # Логуємо завершення запиту
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
        """Отримує справжній IP клієнта."""
        # Перевіряємо заголовки від проксі серверів
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware для обмеження частоти запитів."""

    def __init__(self, app, calls: int = 60, period: int = 60):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.clients = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()

        # Очищуємо старі записи
        if current_time % 60 < 1:  # Кожну хвилину
            self.cleanup_old_entries(current_time)

        # Перевіряємо ліміт
        if client_ip in self.clients:
            requests = self.clients[client_ip]
            recent_requests = [req_time for req_time in requests if current_time - req_time < self.period]

            if len(recent_requests) >= self.calls:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too Many Requests",
                        "message": f"Rate limit exceeded: {self.calls} requests per {self.period} seconds"
                    }
                )

            self.clients[client_ip] = recent_requests + [current_time]
        else:
            self.clients[client_ip] = [current_time]

        return await call_next(request)

    def cleanup_old_entries(self, current_time: float):
        """Очищає старі записи для економії пам'яті."""
        for client_ip in list(self.clients.keys()):
            requests = self.clients[client_ip]
            recent_requests = [req_time for req_time in requests if current_time - req_time < self.period * 2]

            if recent_requests:
                self.clients[client_ip] = recent_requests
            else:
                del self.clients[client_ip]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events для FastAPI додатку."""
    # Startup
    logger.info("🚀 Starting WebCraft Pro API...")
    logger.info(f"🔧 Environment: {settings.ENVIRONMENT}")
    logger.info(f"🗄️  Database: {settings.DB_NAME} on {settings.DB_HOST}")
    logger.info(f"👤 Admin: {settings.ADMIN_EMAIL}")

    try:
        # Ініціалізуємо базу даних
        init_database()

        # Тестуємо email з'єднання якщо налаштовано
        if settings.validate_email_config():
            email_connection_ok = await email_service.test_email_connection()
            if email_connection_ok:
                logger.info("✅ Email service connected")
            else:
                logger.warning("⚠️ Email service connection failed")

        logger.info("✅ Application started successfully!")
        logger.info(f"🌐 Server available at: http://{settings.HOST}:{settings.PORT}")
        logger.info(f"📚 API Documentation: http://{settings.HOST}:{settings.PORT}/docs")

        # Виводимо статистику БД
        db_stats = get_database_stats()
        logger.info(f"📊 Database stats: {db_stats.get('users', 0)} users, {db_stats.get('designs', 0)} designs")

    except Exception as e:
        logger.error(f"❌ Failed to initialize application: {e}")
        import traceback
        traceback.print_exc()
        raise

    yield

    # Shutdown
    logger.info("👋 Application shutting down...")


# Валідуємо налаштування при запуску
try:
    validate_environment()
except Exception as e:
    logger.error(f"Environment validation failed: {e}")
    print(f"❌ Configuration Error: {e}")
    print("💡 Please check your settings and try again.")
    sys.exit(1)


# Створюємо FastAPI додаток
app = FastAPI(
    title="WebCraft Pro API",
    description="""
    🎨 **WebCraft Pro API** - Професійний backend для сайту веб-студії

    ## Основні функції:
    - 🔐 JWT авторизація з cookie підтримкою
    - 🎨 Управління портфоліо дизайнів
    - 💼 Пакети послуг з детальним описом
    - ⭐ Система відгуків з модерацією
    - 📋 Обробка заявок на прорахунок та консультації
    - 📁 Завантаження та оптимізація файлів
    - 🌐 Мультиязичність (UK/EN)
    - 📊 Адмін панель з статистикою
    - 📧 Email сповіщення

    ## Безпека:
    - Rate limiting
    - CORS захист  
    - Валідація даних
    - SQL injection захист
    - XSS захист
    """,
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

# ============ MIDDLEWARE ============

# Додаємо кастомний middleware
app.add_middleware(CustomMiddleware)

# Rate limiting (тільки у продакшн)
if not settings.DEBUG:
    app.add_middleware(
        RateLimitMiddleware,
        calls=settings.RATE_LIMIT_PER_MINUTE,
        period=60
    )

# Gzip стискання
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Trusted hosts (у продакшн)
if settings.is_production():
    trusted_hosts = ["webcraft.pro", "www.webcraft.pro", "api.webcraft.pro"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

# CORS
cors_config = settings.get_cors_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_config["allow_origins"],
    allow_credentials=cors_config["allow_credentials"],
    allow_methods=cors_config["allow_methods"],
    allow_headers=cors_config["allow_headers"],
)


# ============ ОБРОБНИКИ ПОМИЛОК ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Обробник HTTP помилок."""
    logger.warning(f"HTTP {exc.status_code}: {exc.detail} - {request.url}")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": f"HTTP {exc.status_code}",
            "message": exc.detail,
            "path": str(request.url.path),
            "timestamp": int(time.time())
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Обробник помилок валідації."""
    logger.warning(f"Validation error: {exc.errors()} - {request.url}")

    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "message": "Invalid request data",
            "details": exc.errors(),
            "path": str(request.url.path)
        }
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_exception_handler(request: Request, exc: StarletteHTTPException):
    """Обробник Starlette HTTP помилок."""
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "message": "The requested resource was not found",
                "path": str(request.url.path)
            }
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": f"HTTP {exc.status_code}",
            "message": exc.detail if hasattr(exc, 'detail') else "An error occurred"
        }
    )


@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc):
    """Обробник внутрішніх помилок сервера."""
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.error(f"Internal server error [{request_id}]: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred" if settings.is_production() else str(exc),
            "request_id": request_id
        }
    )


# ============ СТАТИЧНІ ФАЙЛИ ============

# Монтуємо статичні файли для завантажених зображень
try:
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
    logger.info(f"Static files mounted: /uploads -> {settings.UPLOAD_DIR}")
except Exception as e:
    logger.warning(f"Failed to mount static files: {e}")


# ============ ОСНОВНІ РОУТИ ============

@app.get("/", tags=["Root"])
async def root():
    """Головна сторінка API з інформацією про сервіс."""
    db_status = "connected" if check_database_connection() else "disconnected"

    return {
        "service": "🎨 WebCraft Pro API",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status,
        "documentation": "/docs" if settings.DEBUG else "Available in development mode",
        "timestamp": int(time.time()),
        "features": {
            "authentication": "JWT with cookies",
            "database": "MySQL with migrations",
            "file_upload": "Images with optimization",
            "email": "SMTP notifications",
            "localization": "Ukrainian/English",
            "admin_panel": "Full CRUD operations",
            "rate_limiting": "60 requests/minute",
            "security": "CORS, XSS, CSRF protection"
        }
    }


@app.get("/health", tags=["System"])
async def health_check():
    """Детальна перевірка стану системи."""
    checks = {}
    overall_status = "healthy"

    # Перевіряємо базу даних
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

    # Перевіряємо email сервіс
    try:
        if settings.validate_email_config():
            checks["email"] = {"status": "configured", "details": "SMTP settings are valid"}
        else:
            checks["email"] = {"status": "not_configured", "details": "SMTP settings missing"}
    except Exception as e:
        checks["email"] = {"status": "error", "details": str(e)}

    # Перевіряємо файлову систему
    try:
        upload_path = Path(settings.UPLOAD_DIR)
        if upload_path.exists() and upload_path.is_dir():
            checks["file_system"] = {"status": "ok", "details": f"Upload directory: {upload_path}"}
        else:
            checks["file_system"] = {"status": "error", "details": "Upload directory not found"}
            overall_status = "degraded"
    except Exception as e:
        checks["file_system"] = {"status": "error", "details": str(e)}

    return {
        "status": overall_status,
        "timestamp": int(time.time()),
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "checks": checks
    }


@app.get("/metrics", tags=["System"])
async def get_metrics():
    """Метрики для моніторингу."""
    if not settings.ENABLE_METRICS:
        raise HTTPException(status_code=404, detail="Metrics disabled")

    try:
        db_stats = get_database_stats()

        metrics = []

        # Database metrics
        for key, value in db_stats.items():
            if isinstance(value, (int, float)) and key != "error":
                metrics.append(f'webcraft_db_{key} {value}')

        # Application metrics
        metrics.extend([
            f'webcraft_app_version{{version="{settings.VERSION}"}} 1',
            f'webcraft_app_debug{{debug="{settings.DEBUG}"}} {int(settings.DEBUG)}',
            f'webcraft_app_environment{{environment="{settings.ENVIRONMENT}"}} 1'
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
    return Response(content="", media_type="image/x-icon")


# ============ API РОУТИ ============

# Підключаємо всі API роути
app.include_router(router, prefix="/api/v1", tags=["API v1"])


# ============ ДОДАТКОВІ РОУТИ ============

@app.get("/api/v1/info", tags=["System"])
async def get_api_info():
    """Інформація про API."""
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "database": {
            "type": "MySQL",
            "name": settings.DB_NAME,
            "host": settings.DB_HOST
        },
        "features": {
            "authentication": True,
            "file_upload": True,
            "email_notifications": settings.validate_email_config(),
            "rate_limiting": True,
            "cors": True
        },
        "limits": {
            "max_file_size": settings.MAX_FILE_SIZE,
            "rate_limit_per_minute": settings.RATE_LIMIT_PER_MINUTE,
            "max_page_size": settings.MAX_PAGE_SIZE
        }
    }


@app.post("/api/v1/test-email", tags=["System"])
async def test_email_endpoint():
    """Тестовий endpoint для перевірки email сервісу (тільки в debug режимі)."""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")

    if not settings.validate_email_config():
        raise HTTPException(status_code=503, detail="Email service not configured")

    try:
        success = await email_service.test_email_connection()
        return {
            "status": "success" if success else "failed",
            "message": "Email connection test completed",
            "configuration": {
                "smtp_server": settings.SMTP_SERVER,
                "smtp_port": settings.SMTP_PORT,
                "use_tls": settings.SMTP_USE_TLS,
                "from_email": settings.FROM_EMAIL
            }
        }
    except Exception as e:
        logger.error(f"Email test error: {e}")
        raise HTTPException(status_code=500, detail=f"Email test failed: {str(e)}")


# ============ ЗАПУСК ДОДАТКУ ============

if __name__ == "__main__":
    # Конфігурація для запуску
    uvicorn_config = {
        "app": "main:app",
        "host": settings.HOST,
        "port": settings.PORT,
        "reload": settings.DEBUG,
        "log_level": "info",
        "access_log": True,
    }

    # Додаткові налаштування для продакшн
    if settings.is_production():
        uvicorn_config.update({
            "workers": 4,  # Кількість worker процесів
            "reload": False,
        })

    logger.info(f"🚀 Starting server with config: {uvicorn_config}")

    try:
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        logger.info("👋 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        sys.exit(1)