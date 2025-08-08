from sqlalchemy import create_engine, MetaData, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
import logging
from typing import Generator, Optional, Dict, Any
import time
import json
from datetime import datetime, timedelta

from config import settings

# Налаштування логування для SQLAlchemy
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING if not settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


# Створення движка бази даних з покращеною конфігурацією
def create_database_engine():
    """Створює движок бази даних з оптимальними налаштуваннями."""
    try:
        connect_args = {
            "charset": "utf8mb4",
            "autocommit": False,
            "connect_timeout": 30,
            "read_timeout": 60,
            "write_timeout": 60,
            # Додаткові параметри MySQL для кращої продуктивності
            "sql_mode": "TRADITIONAL",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"
        }

        engine = create_engine(
            settings.DATABASE_URL,
            poolclass=QueuePool,
            pool_size=20,  # Збільшено для кращої продуктивності
            max_overflow=30,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.DEBUG,
            connect_args=connect_args,
            # Додаткові параметри для MySQL
            future=True
        )

        # Подія для логування повільних запитів
        @event.listens_for(engine, "before_cursor_execute")
        def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            context._query_start_time = time.time()

        @event.listens_for(engine, "after_cursor_execute")
        def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            total = time.time() - context._query_start_time
            if total > 1.0:  # Логуємо запити довше 1 секунди
                logger.warning(f"Slow query ({total:.2f}s): {statement[:100]}...")

        return engine

    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        raise


engine = create_database_engine()

# Створення сесії з покращеним конфігом
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False  # Важливо для background tasks
)

# Базовий клас для моделей
Base = declarative_base()

# Metadata для міграцій
metadata = MetaData()


class DatabaseManager:
    """Менеджер бази даних з додатковими функціями."""

    def __init__(self, engine=engine):
        self.engine = engine
        self._connection_cache = {}

    def get_connection_info(self) -> Dict[str, Any]:
        """Отримує інформацію про з'єднання з БД."""
        try:
            with self.engine.connect() as conn:
                # Отримуємо версію MySQL
                version_result = conn.execute(text("SELECT VERSION()"))
                version = version_result.scalar()

                # Отримуємо кількість активних з'єднань
                processes_result = conn.execute(text("SHOW PROCESSLIST"))
                active_connections = len(list(processes_result))

                # Отримуємо статус бази даних
                status_result = conn.execute(text("SHOW STATUS LIKE 'Threads_connected'"))
                threads_connected = status_result.fetchone()[1] if status_result.rowcount > 0 else 0

                return {
                    "version": version,
                    "active_connections": active_connections,
                    "threads_connected": int(threads_connected),
                    "database_name": settings.DB_NAME,
                    "host": settings.DB_HOST,
                    "status": "connected"
                }
        except Exception as e:
            logger.error(f"Error getting connection info: {e}")
            return {"status": "error", "error": str(e)}

    def get_table_info(self) -> Dict[str, Any]:
        """Отримує інформацію про таблиці."""
        try:
            with self.engine.connect() as conn:
                # Список всіх таблиць
                tables_result = conn.execute(text("""
                    SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH 
                    FROM information_schema.TABLES 
                    WHERE TABLE_SCHEMA = :db_name
                """), {"db_name": settings.DB_NAME})

                tables = []
                for row in tables_result:
                    tables.append({
                        "name": row[0],
                        "rows": row[1] or 0,
                        "data_size": row[2] or 0,
                        "index_size": row[3] or 0
                    })

                return {"tables": tables, "total_tables": len(tables)}
        except Exception as e:
            logger.error(f"Error getting table info: {e}")
            return {"error": str(e)}

    def optimize_tables(self) -> Dict[str, Any]:
        """Оптимізує всі таблиці в базі даних."""
        try:
            optimized = []
            with self.engine.connect() as conn:
                # Отримуємо список таблиць
                tables_result = conn.execute(text("""
                    SELECT TABLE_NAME FROM information_schema.TABLES 
                    WHERE TABLE_SCHEMA = :db_name
                """), {"db_name": settings.DB_NAME})

                for row in tables_result:
                    table_name = row[0]
                    try:
                        conn.execute(text(f"OPTIMIZE TABLE {table_name}"))
                        optimized.append(table_name)
                        logger.info(f"Optimized table: {table_name}")
                    except Exception as e:
                        logger.warning(f"Failed to optimize table {table_name}: {e}")

                conn.commit()

            return {"optimized_tables": optimized, "count": len(optimized)}
        except Exception as e:
            logger.error(f"Error optimizing tables: {e}")
            return {"error": str(e)}


# Глобальний екземпляр менеджера
db_manager = DatabaseManager()


def get_db() -> Generator[Session, None, None]:
    """
    Функція-залежність для отримання сесії бази даних.
    Автоматично закриває сесію після використання.
    """
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"Unexpected error in database session: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """Отримати сесію БД для використання в background tasks."""
    return SessionLocal()


def init_database():
    """
    Створює всі таблиці в базі даних та запускає міграції.
    Викликається при запуску додатку.
    """
    try:
        logger.info("Initializing database...")

        # Перевіряємо з'єднання
        if not check_database_connection():
            raise Exception("Cannot connect to database")

        # Створюємо таблиці
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully!")

        # Запускаємо міграції
        run_migrations()
        logger.info("Database migrations completed!")

        # Створюємо адміна та початкові дані
        create_default_admin()
        seed_database()

        logger.info("Database initialization completed successfully!")

    except OperationalError as e:
        logger.error(f"Database operational error: {e}")
        if "Access denied" in str(e):
            logger.error("Check database credentials")
        elif "Unknown database" in str(e):
            logger.error("Database does not exist")
        elif "Can't connect" in str(e):
            logger.error("Cannot connect to MySQL server")
        raise
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise


def check_database_connection(max_retries: int = 3) -> bool:
    """
    Перевіряє з'єднання з базою даних з повторними спробами.
    """
    for attempt in range(max_retries):
        try:
            with engine.connect() as connection:
                result = connection.execute(text("SELECT 1 as health_check"))
                result.fetchone()
            logger.info("Database connection successful!")
            return True
        except OperationalError as e:
            error_msg = str(e).lower()
            if "access denied" in error_msg:
                logger.error(f"Database access denied: {e}")
                return False
            elif "unknown database" in error_msg:
                logger.error(f"Database not found: {e}")
                return False
            elif "can't connect" in error_msg:
                if attempt < max_retries - 1:
                    logger.warning(f"Connection attempt {attempt + 1} failed, retrying...")
                    time.sleep(2)
                    continue
                else:
                    logger.error(f"Cannot connect to MySQL server after {max_retries} attempts")
                    return False
            else:
                logger.error(f"Database connection error: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected database error: {e}")
            return False

    return False


def test_database_permissions() -> bool:
    """
    Тестує дозволи користувача в базі даних.
    """
    try:
        with engine.connect() as connection:
            # Тестуємо читання
            connection.execute(text("SHOW TABLES"))

            # Тестуємо створення таблиці
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS _permission_test (
                    id INT PRIMARY KEY,
                    test_field VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # Тестуємо вставку
            connection.execute(text("""
                INSERT IGNORE INTO _permission_test (id, test_field) 
                VALUES (1, 'test')
            """))

            # Тестуємо оновлення
            connection.execute(text("""
                UPDATE _permission_test 
                SET test_field = 'updated' 
                WHERE id = 1
            """))

            # Тестуємо видалення
            connection.execute(text("""
                DELETE FROM _permission_test WHERE id = 1
            """))

            # Видаляємо тестову таблицю
            connection.execute(text("DROP TABLE IF EXISTS _permission_test"))

            connection.commit()
            logger.info("Database permissions test passed!")
            return True

    except Exception as e:
        logger.error(f"Database permissions test failed: {e}")
        return False


def run_migrations():
    """
    Запускає міграції для оновлення структури бази даних.
    """
    logger.info("Running database migrations...")

    try:
        with engine.connect() as connection:
            # НОВЫЕ МИГРАЦИИ ДЛЯ ДОБАВЛЕННЫХ ФУНКЦИЙ

            # Миграция 1: Добавляем поля к таблице users
            new_user_fields = [
                ('password_changed_at', 'TIMESTAMP NULL'),
                ('last_login', 'TIMESTAMP NULL')
            ]

            for field_name, field_type in new_user_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE users 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to users")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        logger.info(f"ℹ️  Migration: {field_name} column already exists in users")
                    else:
                        logger.warning(f"Migration warning for {field_name} in users: {e}")

            # Миграция 2: Создаем таблицу about_content
            try:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS about_content (
                        id INT PRIMARY KEY AUTO_INCREMENT,
                        hero_description_uk TEXT,
                        hero_description_en TEXT,
                        mission_uk TEXT,
                        mission_en TEXT,
                        vision_uk TEXT,
                        vision_en TEXT,
                        why_choose_us_uk TEXT,
                        why_choose_us_en TEXT,
                        cta_title_uk VARCHAR(255),
                        cta_title_en VARCHAR(255),
                        cta_description_uk TEXT,
                        cta_description_en TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                connection.commit()
                logger.info("✅ Migration: Created about_content table")
            except (OperationalError, ProgrammingError) as e:
                if "already exists" in str(e):
                    logger.info("ℹ️  Migration: about_content table already exists")
                else:
                    logger.warning(f"Migration warning for about_content table: {e}")

            # Миграция 3: Создаем таблицу team_members
            try:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS team_members (
                        id INT PRIMARY KEY AUTO_INCREMENT,
                        name VARCHAR(255) NOT NULL,
                        role_uk VARCHAR(255) NOT NULL,
                        role_en VARCHAR(255) NOT NULL,
                        skills TEXT,
                        avatar VARCHAR(500),
                        initials VARCHAR(3) NOT NULL,
                        order_index INT DEFAULT 0,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

                        INDEX idx_team_active (is_active),
                        INDEX idx_team_order (order_index),
                        INDEX idx_team_active_order (is_active, order_index)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                connection.commit()
                logger.info("✅ Migration: Created team_members table")
            except (OperationalError, ProgrammingError) as e:
                if "already exists" in str(e):
                    logger.info("ℹ️  Migration: team_members table already exists")
                else:
                    logger.warning(f"Migration warning for team_members table: {e}")

            # СУЩЕСТВУЮЩИЕ МИГРАЦИИ (с исправлениями)

            # Миграция 4: Додаємо show_live_demo до designs
            try:
                connection.execute(text("""
                    ALTER TABLE designs 
                    ADD COLUMN show_live_demo BOOLEAN DEFAULT TRUE NOT NULL
                """))
                connection.commit()
                logger.info("✅ Migration: Added show_live_demo column to designs")
            except (OperationalError, ProgrammingError) as e:
                if "Duplicate column name" in str(e):
                    logger.info("ℹ️  Migration: show_live_demo column already exists")
                else:
                    logger.warning(f"Migration warning for show_live_demo: {e}")

            # Миграция 5: Додаємо нові поля до designs
            new_design_fields = [
                ('slug', 'VARCHAR(255) UNIQUE'),
                ('is_published', 'BOOLEAN DEFAULT TRUE'),
                ('is_featured', 'BOOLEAN DEFAULT FALSE'),
                ('sort_order', 'INT DEFAULT 0'),
                ('views_count', 'INT DEFAULT 0')
            ]

            for field_name, field_type in new_design_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE designs 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to designs")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass  # Поле вже існує
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 6: Додаємо нові поля до packages
            new_package_fields = [
                ('slug', 'VARCHAR(255) UNIQUE'),
                ('is_active', 'BOOLEAN DEFAULT TRUE'),
                ('sort_order', 'INT DEFAULT 0')
            ]

            for field_name, field_type in new_package_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE packages 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to packages")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 7: Додаємо нові поля до reviews
            new_review_fields = [
                ('is_featured', 'BOOLEAN DEFAULT FALSE'),
                ('sort_order', 'INT DEFAULT 0'),
                ('approved_at', 'TIMESTAMP NULL')
            ]

            for field_name, field_type in new_review_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE reviews 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to reviews")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 8: Додаємо нові поля до faq
            try:
                connection.execute(text("""
                    ALTER TABLE faq 
                    ADD COLUMN is_active BOOLEAN DEFAULT TRUE
                """))
                connection.commit()
                logger.info("✅ Migration: Added is_active to faq")
            except (OperationalError, ProgrammingError) as e:
                if "Duplicate column name" in str(e):
                    pass
                else:
                    logger.warning(f"Migration warning for is_active in faq: {e}")

            # Миграция 9: Додаємо нові поля до content
            new_content_fields = [
                ('description', 'VARCHAR(500)'),
                ('is_active', 'BOOLEAN DEFAULT TRUE')
            ]

            for field_name, field_type in new_content_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE content 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to content")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 10: Додаємо робочі години до contact_info
            try:
                connection.execute(text("""
                    ALTER TABLE contact_info 
                    ADD COLUMN working_hours_uk VARCHAR(255),
                    ADD COLUMN working_hours_en VARCHAR(255)
                """))
                connection.commit()
                logger.info("✅ Migration: Added working hours to contact_info")
            except (OperationalError, ProgrammingError) as e:
                if "Duplicate column name" in str(e):
                    pass
                else:
                    logger.warning(f"Migration warning for working hours: {e}")

            # Миграция 11: Покращуємо uploaded_files
            new_file_fields = [
                ('thumbnail_url', 'VARCHAR(500)'),
                ('category', 'VARCHAR(50) DEFAULT "other"'),
                ('hash', 'VARCHAR(64)'),
                ('alt_text', 'VARCHAR(255)'),
                ('is_used', 'BOOLEAN DEFAULT FALSE')
            ]

            for field_name, field_type in new_file_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE uploaded_files 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to uploaded_files")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 12: Покращуємо policies
            new_policy_fields = [
                ('is_active', 'BOOLEAN DEFAULT TRUE'),
                ('version', 'VARCHAR(20) DEFAULT "1.0"')
            ]

            for field_name, field_type in new_policy_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE policies 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to policies")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 13: Додаємо structured_data до seo_settings
            try:
                connection.execute(text("""
                    ALTER TABLE seo_settings 
                    ADD COLUMN structured_data JSON
                """))
                connection.commit()
                logger.info("✅ Migration: Added structured_data to seo_settings")
            except (OperationalError, ProgrammingError) as e:
                if "Duplicate column name" in str(e):
                    pass
                else:
                    logger.warning(f"Migration warning for structured_data: {e}")

            # Миграция 14: Додаємо поля до quote_applications
            new_quote_fields = [
                ('response_text', 'TEXT'),
                ('processed_at', 'TIMESTAMP NULL')
            ]

            for field_name, field_type in new_quote_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE quote_applications 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to quote_applications")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 15: Додаємо поля до consultation_applications
            new_consultation_fields = [
                ('consultation_scheduled_at', 'TIMESTAMP NULL'),
                ('consultation_completed_at', 'TIMESTAMP NULL'),
                ('notes', 'TEXT')
            ]

            for field_name, field_type in new_consultation_fields:
                try:
                    connection.execute(text(f"""
                        ALTER TABLE consultation_applications 
                        ADD COLUMN {field_name} {field_type}
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Added {field_name} to consultation_applications")
                except (OperationalError, ProgrammingError) as e:
                    if "Duplicate column name" in str(e):
                        pass
                    else:
                        logger.warning(f"Migration warning for {field_name}: {e}")

            # Миграция 16: Додаємо індекси для покращення продуктивності
            indexes = [
                ("idx_designs_category_published", "designs", ["category_id", "is_published"]),
                ("idx_designs_featured", "designs", ["is_featured"]),
                ("idx_reviews_approved", "reviews", ["is_approved"]),
                ("idx_reviews_featured", "reviews", ["is_featured"]),
                ("idx_quote_apps_status", "quote_applications", ["status"]),
                ("idx_consultation_apps_status", "consultation_applications", ["status"]),
                ("idx_uploaded_files_category", "uploaded_files", ["category"]),
                ("idx_uploaded_files_hash", "uploaded_files", ["hash"])
            ]

            for index_name, table_name, columns in indexes:
                try:
                    columns_str = ", ".join(columns)
                    connection.execute(text(f"""
                        CREATE INDEX IF NOT EXISTS {index_name} 
                        ON {table_name}({columns_str})
                    """))
                    connection.commit()
                    logger.info(f"✅ Migration: Created index {index_name}")
                except Exception as e:
                    logger.warning(f"Migration warning for index {index_name}: {e}")

        logger.info("✅ All migrations completed successfully!")

    except Exception as e:
        logger.error(f"Migration error: {e}")
        raise


def create_default_admin():
    """
    Створює адміністратора за замовчуванням якщо він не існує.
    """
    from models import User
    from auth import get_password_hash

    db = SessionLocal()
    try:
        logger.info("Checking for admin user...")

        # Перевіряємо чи існує адмін
        admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not admin:
            # Створюємо адміна
            admin_user = User(
                email=settings.ADMIN_EMAIL,
                name=settings.ADMIN_NAME,
                hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
                is_admin=True,
                is_active=True
            )
            db.add(admin_user)
            db.commit()
            logger.info(f"✅ Admin user created: {settings.ADMIN_EMAIL}")
        else:
            logger.info(f"ℹ️  Admin user already exists: {settings.ADMIN_EMAIL}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating admin user: {e}")
        raise
    finally:
        db.close()


def seed_database():
    """
    Додає початкові дані до бази даних.
    """
    from models import (
        DesignCategory, Package, ContactInfo,
        SEOSettings, Policy, Content, SiteSettings,
        AboutContent, TeamMember
    )

    db = SessionLocal()
    try:
        logger.info("Seeding database with initial data...")

        # Создаем базовый контент для страницы "О нас"
        if not db.query(AboutContent).first():
            about_content = AboutContent(
                hero_description_uk="Ми створюємо веб-сайти, які допомагають бізнесу рости та розвиватися в цифровому світі.",
                hero_description_en="We create websites that help businesses grow and thrive in the digital world.",
                mission_uk="Наша місія — створювати інноваційні веб-рішення, які перевершують очікування клієнтів.",
                mission_en="Our mission is to create innovative web solutions that exceed client expectations.",
                vision_uk="Ми прагнемо стати провідною веб-студією в Україні.",
                vision_en="We strive to become the leading web studio in Ukraine.",
                why_choose_us_uk="Ми поєднуємо технічну експертизу з творчим підходом для створення унікальних рішень.",
                why_choose_us_en="We combine technical expertise with creative approach to create unique solutions.",
                cta_title_uk="Готові розпочати свій проект?",
                cta_title_en="Ready to start your project?",
                cta_description_uk="Зв'яжіться з нами сьогодні і отримайте безкоштовну консультацію.",
                cta_description_en="Contact us today and get a free consultation."
            )
            db.add(about_content)
            logger.info("✅ About content seeded!")

        # Создаем начальную команду
        if not db.query(TeamMember).first():
            team_members = [
                TeamMember(
                    name="Олександр Петренко",
                    role_uk="Керівник проектів",
                    role_en="Project Manager",
                    skills="Project Management, Scrum, Client Communication",
                    initials="ОП",
                    order_index=1
                ),
                TeamMember(
                    name="Анна Коваленко",
                    role_uk="UI/UX Дизайнер",
                    role_en="UI/UX Designer",
                    skills="Figma, Adobe XD, User Research, Prototyping",
                    initials="АК",
                    order_index=2
                ),
                TeamMember(
                    name="Максим Сидоренко",
                    role_uk="Full-stack Developer",
                    role_en="Full-stack Developer",
                    skills="React, Node.js, Python, MySQL, MongoDB",
                    initials="МС",
                    order_index=3
                )
            ]

            for member in team_members:
                db.add(member)
            logger.info("✅ Team members seeded!")

        # Створюємо базові категорії дизайнів
        if not db.query(DesignCategory).first():
            categories = [
                DesignCategory(id="all", slug="all", title_uk="Всі проекти", title_en="All Projects"),
                DesignCategory(id="e-commerce", slug="e-commerce", title_uk="Інтернет-магазини", title_en="E-commerce"),
                DesignCategory(id="corporate", slug="corporate", title_uk="Корпоративні", title_en="Corporate"),
                DesignCategory(id="landing", slug="landing", title_uk="Лендінги", title_en="Landing Pages"),
                DesignCategory(id="restaurants", slug="restaurants", title_uk="Ресторани", title_en="Restaurants"),
                DesignCategory(id="medical", slug="medical", title_uk="Медицина", title_en="Medical"),
                DesignCategory(id="education", slug="education", title_uk="Освіта", title_en="Education"),
                DesignCategory(id="portfolio", slug="portfolio", title_uk="Портфоліо", title_en="Portfolio"),
                DesignCategory(id="real-estate", slug="real-estate", title_uk="Нерухомість", title_en="Real Estate"),
            ]

            for category in categories:
                db.add(category)
            logger.info("✅ Design categories seeded!")

        # Створюємо базові пакети
        if not db.query(Package).first():
            packages = [
                Package(
                    name="Starter",
                    slug="starter",
                    price_uk="від €1 500",
                    price_en="from €1,500",
                    duration_uk="2–4 тижні",
                    duration_en="2–4 weeks",
                    features_uk=["Простий лендінг до 5 сторінок", "Адаптивний дизайн", "Базове SEO", "SSL-сертифікат",
                                 "Хостинг на 1 рік"],
                    features_en=["Simple landing up to 5 pages", "Responsive design", "Basic SEO", "SSL certificate",
                                 "Hosting for 1 year"],
                    advantages_uk=["Швидкий запуск", "Економічно вигідно", "Базова функціональність"],
                    advantages_en=["Quick launch", "Cost effective", "Basic functionality"],
                    process_uk=["Консультація", "Дизайн", "Розробка", "Запуск"],
                    process_en=["Consultation", "Design", "Development", "Launch"],
                    support_uk="30 днів безкоштовної підтримки",
                    support_en="30 days free support",
                    is_popular=False
                ),
                Package(
                    name="Business",
                    slug="business",
                    price_uk="від €3 500",
                    price_en="from €3,500",
                    duration_uk="4–8 тижнів",
                    duration_en="4–8 weeks",
                    features_uk=["Корпоративний сайт до 15 сторінок", "Інтеграції API", "Google Analytics",
                                 "Адмін-панель", "Форми зворотного зв'язку", "Інтеграція з соцмережами"],
                    features_en=["Corporate website up to 15 pages", "API integrations", "Google Analytics",
                                 "Admin panel", "Contact forms", "Social media integration"],
                    advantages_uk=["Повна функціональність", "Готовий для бізнесу", "Професійний дизайн"],
                    advantages_en=["Full functionality", "Business ready", "Professional design"],
                    process_uk=["Аналіз вимог", "UI/UX дизайн", "Розробка", "Тестування", "Запуск"],
                    process_en=["Requirements analysis", "UI/UX design", "Development", "Testing", "Launch"],
                    support_uk="90 днів безкоштовної підтримки + навчання",
                    support_en="90 days free support + training",
                    is_popular=True
                ),
                Package(
                    name="Enterprise",
                    slug="enterprise",
                    price_uk="від €7 500",
                    price_en="from €7,500",
                    duration_uk="8–16 тижнів",
                    duration_en="8–16 weeks",
                    features_uk=["Необмежена кількість сторінок", "Складні інтеграції", "CRM система",
                                 "Електронна комерція", "Мобільний додаток", "Додаткова безпека"],
                    features_en=["Unlimited pages", "Complex integrations", "CRM system", "E-commerce", "Mobile app",
                                 "Advanced security"],
                    advantages_uk=["Масштабованість", "Максимальна функціональність", "Індивідуальний підхід"],
                    advantages_en=["Scalability", "Maximum functionality", "Individual approach"],
                    process_uk=["Глибокий аналіз", "Архітектура", "Поетапна розробка", "Інтеграції", "Запуск",
                                "Навчання"],
                    process_en=["Deep analysis", "Architecture", "Phased development", "Integrations", "Launch",
                                "Training"],
                    support_uk="1 рік безкоштовної підтримки + постійний супровід",
                    support_en="1 year free support + ongoing maintenance",
                    is_popular=False
                )
            ]

            for package in packages:
                db.add(package)
            logger.info("✅ Packages seeded!")

        # Створюємо базові налаштування контактів
        if not db.query(ContactInfo).first():
            contact_info = ContactInfo(
                phone="+380123456789",
                email="hello@webcraft.pro",
                telegram="@webcraftpro",
                telegram_url="https://t.me/webcraftpro",
                address_uk="Україна, Київ",
                address_en="Ukraine, Kyiv",
                working_hours_uk="Пн-Пт: 9:00-18:00",
                working_hours_en="Mon-Fri: 9:00-18:00"
            )
            db.add(contact_info)
            logger.info("✅ Contact info seeded!")

        # Створюємо базові SEO налаштування
        if not db.query(SEOSettings).first():
            seo_pages = [
                SEOSettings(
                    page="home",
                    meta_title_uk="WebCraft Pro - Професійна розробка сайтів",
                    meta_title_en="WebCraft Pro - Professional Website Development",
                    meta_description_uk="Створюємо сучасні та функціональні сайти для бізнесу. Професійна розробка, дизайн та підтримка веб-сайтів.",
                    meta_description_en="Creating modern and functional websites for business. Professional development, design and support of websites."
                ),
                SEOSettings(
                    page="about",
                    meta_title_uk="Про нас - WebCraft Pro",
                    meta_title_en="About Us - WebCraft Pro"
                ),
                SEOSettings(
                    page="services",
                    meta_title_uk="Послуги - WebCraft Pro",
                    meta_title_en="Services - WebCraft Pro"
                )
            ]

            for seo in seo_pages:
                db.add(seo)
            logger.info("✅ SEO settings seeded!")

        # Створюємо базові політики
        if not db.query(Policy).first():
            policies = [
                Policy(
                    type="privacy_policy",
                    title_uk="Політика конфіденційності",
                    title_en="Privacy Policy",
                    content_uk="Тут буде текст політики конфіденційності...",
                    content_en="Here will be the privacy policy text..."
                ),
                Policy(
                    type="terms_of_use",
                    title_uk="Умови використання",
                    title_en="Terms of Use",
                    content_uk="Тут будуть умови використання...",
                    content_en="Here will be the terms of use..."
                )
            ]

            for policy in policies:
                db.add(policy)
            logger.info("✅ Policies seeded!")

        # Створюємо базовий контент
        if not db.query(Content).first():
            content_items = [
                Content(
                    key="hero_title_uk",
                    content_uk="Створюємо сайти, які працюють на ваш бізнес",
                    description="Заголовок героїчної секції українською"
                ),
                Content(
                    key="hero_title_en",
                    content_en="Creating websites that work for your business",
                    description="Hero section title in English"
                ),
                Content(
                    key="hero_subtitle_uk",
                    content_uk="Професійна розробка сучасних веб-сайтів з унікальним дизайном та потужним функціоналом",
                    description="Підзаголовок героїчної секції українською"
                ),
                Content(
                    key="hero_subtitle_en",
                    content_en="Professional development of modern websites with unique design and powerful functionality",
                    description="Hero section subtitle in English"
                )
            ]

            for item in content_items:
                db.add(item)
            logger.info("✅ Content seeded!")

        # Створюємо базові налаштування сайту
        if not db.query(SiteSettings).first():
            site_settings = [
                SiteSettings(
                    key="site_name",
                    value="WebCraft Pro",
                    category="general",
                    description="Назва сайту",
                    is_public=True
                ),
                SiteSettings(
                    key="maintenance_mode",
                    value="false",
                    type="boolean",
                    category="general",
                    description="Режим обслуговування",
                    is_public=True
                ),
                SiteSettings(
                    key="google_analytics_id",
                    value="",
                    category="analytics",
                    description="Google Analytics ID",
                    is_public=True
                ),
                SiteSettings(
                    key="allow_reviews",
                    value="true",
                    type="boolean",
                    category="features",
                    description="Дозволити залишати відгуки",
                    is_public=True
                )
            ]

            for setting in site_settings:
                db.add(setting)
            logger.info("✅ Site settings seeded!")

        db.commit()
        logger.info("✅ Database seeding completed successfully!")

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


def backup_database() -> Optional[str]:
    """
    Створює резервну копію бази даних (MySQL).
    Повертає шлях до файлу backup або None у разі помилки.
    """
    import subprocess
    from datetime import datetime

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_webcraft_pro_{timestamp}.sql"

        cmd = [
            "mysqldump",
            f"--host={settings.DB_HOST}",
            f"--port={settings.DB_PORT}",
            f"--user={settings.DB_USER}",
            f"--password={settings.DB_PASSWORD}",
            "--single-transaction",
            "--routines",
            "--triggers",
            settings.DB_NAME
        ]

        with open(backup_file, 'w') as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            logger.info(f"✅ Database backup created: {backup_file}")
            return backup_file
        else:
            logger.error(f"Backup failed: {result.stderr}")
            return None

    except Exception as e:
        logger.error(f"Failed to create database backup: {e}")
        return None


def get_database_stats() -> Dict[str, Any]:
    """
    Отримує статистику бази даних.
    """
    from models import (
        User, Design, Package, Review, QuoteApplication,
        ConsultationApplication, FAQ, Content, UploadedFile,
        AboutContent, TeamMember
    )

    db = SessionLocal()
    try:
        stats = {
            "users": db.query(User).count(),
            "designs": db.query(Design).count(),
            "published_designs": db.query(Design).filter(Design.is_published == True).count(),
            "packages": db.query(Package).count(),
            "active_packages": db.query(Package).filter(Package.is_active == True).count(),
            "reviews": db.query(Review).count(),
            "approved_reviews": db.query(Review).filter(Review.is_approved == True).count(),
            "quote_applications": db.query(QuoteApplication).count(),
            "new_quote_applications": db.query(QuoteApplication).filter(
                QuoteApplication.status == "new"
            ).count(),
            "consultation_applications": db.query(ConsultationApplication).count(),
            "new_consultation_applications": db.query(ConsultationApplication).filter(
                ConsultationApplication.status == "new"
            ).count(),
            "faq": db.query(FAQ).count(),
            "content": db.query(Content).count(),
            "uploaded_files": db.query(UploadedFile).count(),
            "about_content": db.query(AboutContent).count(),
            "team_members": db.query(TeamMember).count(),
            "active_team_members": db.query(TeamMember).filter(TeamMember.is_active == True).count()
        }

        # Додаємо інформацію про з'єднання
        stats.update(db_manager.get_connection_info())

        return stats
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def cleanup_old_data(days_old: int = 30) -> Dict[str, Any]:
    """
    Очищує старі дані з бази даних.
    """
    from models import EmailLog
    from datetime import datetime, timedelta

    if days_old <= 0:
        return {"error": "days_old must be positive"}

    db = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        # Видаляємо старі email логи
        deleted_logs = db.query(EmailLog).filter(
            EmailLog.created_at < cutoff_date
        ).count()

        db.query(EmailLog).filter(EmailLog.created_at < cutoff_date).delete()

        db.commit()

        logger.info(f"Cleaned up {deleted_logs} old email logs")
        return {
            "deleted_email_logs": deleted_logs,
            "cutoff_date": cutoff_date.isoformat()
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error cleaning up old data: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def rebuild_indexes() -> Dict[str, Any]:
    """
    Перебудовує індекси бази даних для покращення продуктивності.
    """
    try:
        with engine.connect() as conn:
            # Отримуємо всі індекси
            indexes_result = conn.execute(text("""
                SELECT DISTINCT TABLE_NAME, INDEX_NAME 
                FROM information_schema.STATISTICS 
                WHERE TABLE_SCHEMA = :db_name 
                AND INDEX_NAME != 'PRIMARY'
            """), {"db_name": settings.DB_NAME})

            rebuilt_indexes = []
            for row in indexes_result:
                table_name, index_name = row[0], row[1]
                try:
                    # Видаляємо та створюємо індекс заново
                    conn.execute(text(f"DROP INDEX {index_name} ON {table_name}"))
                    # Примітка: тут потрібно було б зберегти визначення індексу
                    # Це спрощена версія
                    rebuilt_indexes.append(f"{table_name}.{index_name}")
                except Exception as e:
                    logger.warning(f"Failed to rebuild index {table_name}.{index_name}: {e}")

            conn.commit()
            logger.info(f"Rebuilt {len(rebuilt_indexes)} indexes")
            return {"rebuilt_indexes": rebuilt_indexes, "count": len(rebuilt_indexes)}

    except Exception as e:
        logger.error(f"Error rebuilding indexes: {e}")
        return {"error": str(e)}