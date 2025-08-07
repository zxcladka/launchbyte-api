#!/usr/bin/env python3
"""
Скрипт запуску WebCraft Pro API з повними перевірками
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# Додаємо поточну директорію до sys.path
sys.path.append(str(Path(__file__).parent))


def print_header():
    """Виводить заголовок."""
    print("=" * 70)
    print("🚀 WEBCRAFT PRO API STARTUP CHECKER")
    print("=" * 70)


def check_python_version():
    """Перевіряє версію Python."""
    print("🔍 Checking Python version...")
    version = sys.version_info
    if version.major != 3 or version.minor < 8:
        print(f"❌ Python 3.8+ required, got {version.major}.{version.minor}")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_env_file():
    """Перевіряє наявність .env файлу."""
    print("🔍 Checking .env file...")
    env_path = Path(".env")
    if not env_path.exists():
        print("⚠️  .env file not found")
        print("💡 Creating .env template...")
        create_env_template()
        return False
    print("✅ .env file found")
    return True


def create_env_template():
    """Створює шаблон .env файлу."""
    template = """# =============================================================================
# WEBCRAFT PRO - НАЛАШТУВАННЯ СЕРЕДОВИЩА
# =============================================================================
# ВАЖЛИВО: Заповніть всі значення перед запуском!

# НАЛАШТУВАННЯ БАЗИ ДАНИХ
DB_HOST=localhost
DB_PORT=3306
DB_USER=webcraft_user
DB_PASSWORD=webcraft_user
DB_NAME=webcraft_pro

# БЕЗПЕКА JWT - ОБОВ'ЯЗКОВО ЗМІНІТЬ!
SECRET_KEY=CHANGE-THIS-TO-SECURE-SECRET-KEY-256-BITS-MINIMUM
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# АДМІНІСТРАТОР - ОБОВ'ЯЗКОВО ЗМІНІТЬ!
ADMIN_EMAIL=admin@webcraft.pro
ADMIN_PASSWORD=CHANGE-THIS-PASSWORD
ADMIN_NAME=Administrator

# НАЛАШТУВАННЯ ДОДАТКУ
DEBUG=true
HOST=127.0.0.1
PORT=8000
"""
    with open(".env", "w") as f:
        f.write(template)
    print("📄 Created .env template - please fill in the values!")


def check_mysql_connection():
    """Перевіряє підключення до MySQL."""
    print("🔍 Checking MySQL connection...")
    try:
        # Завантажуємо налаштування
        from dotenv import load_dotenv
        load_dotenv()

        from config import settings
        from database import check_database_connection

        if check_database_connection():
            print("✅ MySQL connection successful")
            return True
        else:
            print("❌ MySQL connection failed")
            print_mysql_troubleshooting()
            return False
    except Exception as e:
        print(f"❌ Error checking MySQL: {e}")
        print_mysql_troubleshooting()
        return False


def print_mysql_troubleshooting():
    """Виводить поради по усуненню проблем з MySQL."""
    print("\n🔧 MySQL Troubleshooting:")
    print("1. Check if MySQL server is running:")
    print("   sudo systemctl status mysql")
    print("2. Check user and database exist:")
    print("   mysql -u root -p")
    print("   SHOW DATABASES;")
    print("   SELECT User, Host FROM mysql.user WHERE User='webcraft_user';")
    print("3. Grant permissions:")
    print("   GRANT ALL PRIVILEGES ON webcraft_pro.* TO 'webcraft_user'@'localhost';")
    print("   FLUSH PRIVILEGES;")


def check_dependencies():
    """Перевіряє залежності Python."""
    print("🔍 Checking Python dependencies...")
    try:
        import fastapi
        import sqlalchemy
        import pymysql
        import uvicorn
        print("✅ All dependencies installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("💡 Install with: pip install -r requirements.txt")
        return False


def check_directories():
    """Перевіряє необхідні директорії."""
    print("🔍 Checking directories...")
    directories = ["uploads", "uploads/images", "uploads/documents", "uploads/other"]

    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)

    print("✅ All directories ready")
    return True


def check_configuration():
    """Перевіряє конфігурацію."""
    print("🔍 Checking configuration...")
    try:
        from dotenv import load_dotenv
        load_dotenv()

        from config import settings

        # Перевіряємо критичні налаштування
        critical_settings = {
            'DB_HOST': settings.DB_HOST,
            'DB_USER': settings.DB_USER,
            'DB_PASSWORD': settings.DB_PASSWORD,
            'DB_NAME': settings.DB_NAME,
            'SECRET_KEY': settings.SECRET_KEY,
            'ADMIN_PASSWORD': settings.ADMIN_PASSWORD
        }

        missing = []
        weak_defaults = []

        for key, value in critical_settings.items():
            if not value:
                missing.append(key)
            elif key == 'SECRET_KEY' and 'CHANGE' in value.upper():
                weak_defaults.append(key)
            elif key == 'ADMIN_PASSWORD' and 'CHANGE' in value.upper():
                weak_defaults.append(key)

        if missing:
            print(f"❌ Missing required settings: {', '.join(missing)}")
            return False

        if weak_defaults:
            print(f"⚠️  Weak default values detected: {', '.join(weak_defaults)}")
            print("💡 Please change default passwords and secret keys!")

        print("✅ Configuration valid")
        return True

    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False


def run_migrations():
    """Запускає міграції."""
    print("🔍 Running database migrations...")
    try:
        from migrate import main as run_migrate
        run_migrate()
        return True
    except Exception as e:
        print(f"⚠️  Migration warning: {e}")
        print("💡 Migrations will run automatically on startup")
        return True


def start_server():
    """Запускає сервер."""
    print("\n🚀 Starting WebCraft Pro API server...")
    print("=" * 70)

    try:
        import uvicorn
        from main import app
        from config import settings

        uvicorn.run(
            "main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=settings.DEBUG,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)


def main():
    """Головна функція."""
    print_header()

    checks = [
        ("Python Version", check_python_version),
        ("Environment File", check_env_file),
        ("Dependencies", check_dependencies),
        ("Configuration", check_configuration),
        ("Directories", check_directories),
        ("MySQL Connection", check_mysql_connection),
    ]

    print("🔍 Running pre-startup checks...\n")

    failed_checks = []

    for check_name, check_func in checks:
        try:
            if not check_func():
                failed_checks.append(check_name)
                print()
        except Exception as e:
            print(f"❌ {check_name} check failed: {e}")
            failed_checks.append(check_name)
        print()

    if failed_checks:
        print("❌ STARTUP FAILED")
        print(f"Failed checks: {', '.join(failed_checks)}")
        print("\n💡 Please fix the issues above and try again.")
        sys.exit(1)

    print("✅ ALL CHECKS PASSED!")
    print("🎉 Starting server...\n")

    # Пауза для читабельності
    time.sleep(1)

    start_server()


if __name__ == "__main__":
    main()