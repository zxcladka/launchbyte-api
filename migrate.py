#!/usr/bin/env python3
"""
WebCraft Pro - Інструмент міграції бази даних
Розширений скрипт для безпечного оновлення структури БД
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, text, inspect, MetaData, Table
from sqlalchemy.exc import OperationalError, ProgrammingError
import logging

# Додаємо поточну директорію до sys.path
sys.path.append(str(Path(__file__).parent))

from config import settings, validate_environment
from database import SessionLocal, Base, get_database_stats

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('migrations.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


class Migration:
    """Клас для представлення міграції."""

    def __init__(self, version: str, name: str, description: str):
        self.version = version
        self.name = name
        self.description = description
        self.executed_at: Optional[datetime] = None
        self.success = False
        self.error_message: Optional[str] = None

    def __str__(self):
        status = "✅" if self.success else "❌" if self.error_message else "⏳"
        return f"{status} {self.version}: {self.name}"


class DatabaseMigrator:
    """Головний клас для управління міграціями."""

    def __init__(self, dry_run: bool = False):
        try:
            validate_environment()
            self.engine = create_engine(settings.DATABASE_URL)
            self.db = SessionLocal()
            self.inspector = inspect(self.engine)
            self.dry_run = dry_run
            self.metadata = MetaData()

            # Створюємо таблицю для відстеження міграцій
            self._ensure_migration_table()

        except Exception as e:
            logger.error(f"Failed to initialize migrator: {e}")
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def _ensure_migration_table(self):
        """Створює таблицю для відстеження міграцій."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        version VARCHAR(50) NOT NULL UNIQUE,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        execution_time_ms INT,
                        success BOOLEAN DEFAULT TRUE,
                        error_message TEXT,
                        rollback_sql TEXT,
                        INDEX idx_version (version),
                        INDEX idx_executed_at (executed_at)
                    )
                """))
                connection.commit()
                logger.info("Schema migrations table ensured")
        except Exception as e:
            logger.error(f"Failed to create schema_migrations table: {e}")
            raise

    def get_executed_migrations(self) -> List[str]:
        """Отримує список виконаних міграцій."""
        try:
            with self.engine.connect() as connection:
                result = connection.execute(text("""
                    SELECT version FROM schema_migrations 
                    WHERE success = TRUE 
                    ORDER BY executed_at
                """))
                return [row[0] for row in result]
        except Exception as e:
            logger.error(f"Failed to get executed migrations: {e}")
            return []

    def record_migration(self, migration: Migration, execution_time_ms: int, rollback_sql: str = ""):
        """Записує інформацію про виконану міграцію."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("""
                    INSERT INTO schema_migrations 
                    (version, name, description, execution_time_ms, success, error_message, rollback_sql)
                    VALUES (:version, :name, :description, :execution_time_ms, :success, :error_message, :rollback_sql)
                    ON DUPLICATE KEY UPDATE
                    executed_at = CURRENT_TIMESTAMP,
                    execution_time_ms = :execution_time_ms,
                    success = :success,
                    error_message = :error_message
                """), {
                    "version": migration.version,
                    "name": migration.name,
                    "description": migration.description,
                    "execution_time_ms": execution_time_ms,
                    "success": migration.success,
                    "error_message": migration.error_message,
                    "rollback_sql": rollback_sql
                })
                connection.commit()
        except Exception as e:
            logger.error(f"Failed to record migration: {e}")

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Перевіряє чи існує колонка в таблиці."""
        try:
            columns = [col['name'] for col in self.inspector.get_columns(table_name)]
            return column_name in columns
        except Exception:
            return False

    def table_exists(self, table_name: str) -> bool:
        """Перевіряє чи існує таблиця."""
        return self.inspector.has_table(table_name)

    def index_exists(self, table_name: str, index_name: str) -> bool:
        """Перевіряє чи існує індекс."""
        try:
            indexes = self.inspector.get_indexes(table_name)
            return any(idx['name'] == index_name for idx in indexes)
        except Exception:
            return False

    def execute_sql(self, sql: str, params: Dict[str, Any] = None, description: str = "") -> bool:
        """Виконує SQL запит з обробкою помилок."""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would execute: {description}")
                logger.debug(f"[DRY RUN] SQL: {sql}")
                return True

            with self.engine.connect() as connection:
                if params:
                    connection.execute(text(sql), params)
                else:
                    connection.execute(text(sql))
                connection.commit()

            logger.info(f"✅ {description}")
            return True

        except (OperationalError, ProgrammingError) as e:
            error_msg = str(e).lower()
            if any(phrase in error_msg for phrase in ["duplicate column", "already exists", "duplicate key"]):
                logger.info(f"ℹ️  {description} (already exists)")
                return True
            else:
                logger.error(f"❌ Failed: {description} - {e}")
                return False
        except Exception as e:
            logger.error(f"❌ Error: {description} - {e}")
            return False

    def get_migration_definitions(self) -> List[Migration]:
        """Повертає список всіх доступних міграцій."""
        migrations = [
            Migration("001", "add_show_live_demo_to_designs",
                      "Додає поле show_live_demo до таблиці designs"),

            Migration("002", "add_design_enhancement_fields",
                      "Додає додаткові поля до таблиці designs (slug, is_published, etc.)"),

            Migration("003", "add_package_enhancement_fields",
                      "Додає додаткові поля до таблиці packages (slug, is_active, etc.)"),

            Migration("004", "add_review_enhancement_fields",
                      "Додає додаткові поля до таблиці reviews (is_featured, approved_at, etc.)"),

            Migration("005", "add_faq_enhancement_fields",
                      "Додає поле is_active до таблиці faq"),

            Migration("006", "add_content_enhancement_fields",
                      "Додає додаткові поля до таблиці content"),

            Migration("007", "add_contact_info_working_hours",
                      "Додає робочі години до таблиці contact_info"),

            Migration("008", "enhance_uploaded_files_table",
                      "Покращує структуру таблиці uploaded_files"),

            Migration("009", "enhance_policies_table",
                      "Додає додаткові поля до таблиці policies"),

            Migration("010", "add_structured_data_to_seo",
                      "Додає structured_data поле до таблиці seo_settings"),

            Migration("011", "add_quote_application_fields",
                      "Додає додаткові поля до таблиці quote_applications"),

            Migration("012", "add_consultation_application_fields",
                      "Додає додаткові поля до таблиці consultation_applications"),

            Migration("013", "create_performance_indexes",
                      "Створює індекси для покращення продуктивності"),

            Migration("014", "create_site_settings_table",
                      "Створює таблицю site_settings для налаштувань"),

            Migration("015", "create_email_tables",
                      "Створює таблиці для email системи"),

            Migration("016", "create_site_stats_table",
                      "Створює таблицю для статистики сайту"),

            Migration("017", "add_category_active_field",
                      "Додає поле is_active до таблиці design_categories"),

            Migration("018", "optimize_database_settings",
                      "Оптимізує налаштування бази даних"),
        ]

        return migrations

    def migration_001_add_show_live_demo_to_designs(self) -> bool:
        """Міграція 001: Додаємо поле show_live_demo до таблиці designs."""
        if not self.table_exists('designs'):
            logger.warning("Table 'designs' does not exist, skipping...")
            return True

        if self.column_exists('designs', 'show_live_demo'):
            logger.info("Column 'show_live_demo' already exists in designs table")
            return True

        sql = """
            ALTER TABLE designs 
            ADD COLUMN show_live_demo BOOLEAN DEFAULT TRUE NOT NULL
        """

        return self.execute_sql(sql, description="Added show_live_demo column to designs table")

    def migration_002_add_design_enhancement_fields(self) -> bool:
        """Міграція 002: Додаємо додаткові поля до таблиці designs."""
        if not self.table_exists('designs'):
            return True

        fields = [
            ('slug', 'VARCHAR(255) UNIQUE'),
            ('is_published', 'BOOLEAN DEFAULT TRUE'),
            ('is_featured', 'BOOLEAN DEFAULT FALSE'),
            ('sort_order', 'INT DEFAULT 0'),
            ('views_count', 'INT DEFAULT 0')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('designs', field_name):
                sql = f"ALTER TABLE designs ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to designs"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_003_add_package_enhancement_fields(self) -> bool:
        """Міграція 003: Додаємо додаткові поля до таблиці packages."""
        if not self.table_exists('packages'):
            return True

        fields = [
            ('slug', 'VARCHAR(255) UNIQUE'),
            ('is_active', 'BOOLEAN DEFAULT TRUE'),
            ('sort_order', 'INT DEFAULT 0')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('packages', field_name):
                sql = f"ALTER TABLE packages ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to packages"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_004_add_review_enhancement_fields(self) -> bool:
        """Міграція 004: Додаємо додаткові поля до таблиці reviews."""
        if not self.table_exists('reviews'):
            return True

        fields = [
            ('is_featured', 'BOOLEAN DEFAULT FALSE'),
            ('sort_order', 'INT DEFAULT 0'),
            ('approved_at', 'TIMESTAMP NULL')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('reviews', field_name):
                sql = f"ALTER TABLE reviews ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to reviews"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_005_add_faq_enhancement_fields(self) -> bool:
        """Міграція 005: Додаємо поле is_active до таблиці faq."""
        if not self.table_exists('faq'):
            return True

        if self.column_exists('faq', 'is_active'):
            return True

        sql = "ALTER TABLE faq ADD COLUMN is_active BOOLEAN DEFAULT TRUE"
        return self.execute_sql(sql, description="Added is_active to faq")

    def migration_006_add_content_enhancement_fields(self) -> bool:
        """Міграція 006: Додаємо додаткові поля до таблиці content."""
        if not self.table_exists('content'):
            return True

        fields = [
            ('description', 'VARCHAR(500)'),
            ('is_active', 'BOOLEAN DEFAULT TRUE')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('content', field_name):
                sql = f"ALTER TABLE content ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to content"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_007_add_contact_info_working_hours(self) -> bool:
        """Міграція 007: Додаємо робочі години до таблиці contact_info."""
        if not self.table_exists('contact_info'):
            return True

        fields = [
            ('working_hours_uk', 'VARCHAR(255)'),
            ('working_hours_en', 'VARCHAR(255)')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('contact_info', field_name):
                sql = f"ALTER TABLE contact_info ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to contact_info"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_008_enhance_uploaded_files_table(self) -> bool:
        """Міграція 008: Покращує структуру таблиці uploaded_files."""
        if not self.table_exists('uploaded_files'):
            return True

        fields = [
            ('thumbnail_url', 'VARCHAR(500)'),
            ('category', 'VARCHAR(50) DEFAULT "other"'),
            ('hash', 'VARCHAR(64)'),
            ('alt_text', 'VARCHAR(255)'),
            ('is_used', 'BOOLEAN DEFAULT FALSE')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('uploaded_files', field_name):
                sql = f"ALTER TABLE uploaded_files ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to uploaded_files"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_009_enhance_policies_table(self) -> bool:
        """Міграція 009: Додаємо додаткові поля до таблиці policies."""
        if not self.table_exists('policies'):
            return True

        fields = [
            ('is_active', 'BOOLEAN DEFAULT TRUE'),
            ('version', 'VARCHAR(20) DEFAULT "1.0"')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('policies', field_name):
                sql = f"ALTER TABLE policies ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to policies"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_010_add_structured_data_to_seo(self) -> bool:
        """Міграція 010: Додаємо structured_data поле до таблиці seo_settings."""
        if not self.table_exists('seo_settings'):
            return True

        if self.column_exists('seo_settings', 'structured_data'):
            return True

        sql = "ALTER TABLE seo_settings ADD COLUMN structured_data JSON"
        return self.execute_sql(sql, description="Added structured_data to seo_settings")

    def migration_011_add_quote_application_fields(self) -> bool:
        """Міграція 011: Додаємо додаткові поля до таблиці quote_applications."""
        if not self.table_exists('quote_applications'):
            return True

        fields = [
            ('response_text', 'TEXT'),
            ('processed_at', 'TIMESTAMP NULL')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('quote_applications', field_name):
                sql = f"ALTER TABLE quote_applications ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to quote_applications"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_012_add_consultation_application_fields(self) -> bool:
        """Міграція 012: Додаємо додаткові поля до таблиці consultation_applications."""
        if not self.table_exists('consultation_applications'):
            return True

        fields = [
            ('consultation_scheduled_at', 'TIMESTAMP NULL'),
            ('consultation_completed_at', 'TIMESTAMP NULL'),
            ('notes', 'TEXT')
        ]

        success_count = 0
        for field_name, field_type in fields:
            if not self.column_exists('consultation_applications', field_name):
                sql = f"ALTER TABLE consultation_applications ADD COLUMN {field_name} {field_type}"
                if self.execute_sql(sql, description=f"Added {field_name} to consultation_applications"):
                    success_count += 1
            else:
                success_count += 1

        return success_count == len(fields)

    def migration_013_create_performance_indexes(self) -> bool:
        """Міграція 013: Створює індекси для покращення продуктивності."""
        indexes = [
            ("idx_designs_category_published", "designs", "category, is_published"),
            ("idx_designs_featured", "designs", "is_featured"),
            ("idx_designs_published_sort", "designs", "is_published, sort_order"),
            ("idx_reviews_approved", "reviews", "approved"),
            ("idx_reviews_featured", "reviews", "is_featured"),
            ("idx_reviews_approved_featured", "reviews", "approved, is_featured"),
            ("idx_quote_apps_status", "quote_applications", "status"),
            ("idx_quote_apps_created", "quote_applications", "created_at"),
            ("idx_consultation_apps_status", "consultation_applications", "status"),
            ("idx_consultation_apps_created", "consultation_applications", "created_at"),
            ("idx_uploaded_files_category", "uploaded_files", "category"),
            ("idx_uploaded_files_hash", "uploaded_files", "hash"),
            ("idx_content_key", "content", "key"),
            ("idx_content_active", "content", "is_active"),
            ("idx_faq_order", "faq", "`order`, id")
        ]

        success_count = 0
        for index_name, table_name, columns in indexes:
            if self.table_exists(table_name):
                if not self.index_exists(table_name, index_name):
                    sql = f"CREATE INDEX {index_name} ON {table_name}({columns})"
                    if self.execute_sql(sql, description=f"Created index {index_name}"):
                        success_count += 1
                else:
                    success_count += 1

        return success_count > 0  # Принаймні один індекс створено або існував

    def migration_014_create_site_settings_table(self) -> bool:
        """Міграція 014: Створює таблицю site_settings для налаштувань."""
        if self.table_exists('site_settings'):
            return True

        sql = """
            CREATE TABLE site_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                `key` VARCHAR(100) NOT NULL UNIQUE,
                value TEXT,
                type VARCHAR(50) DEFAULT 'string',
                category VARCHAR(50) DEFAULT 'general',
                description VARCHAR(500),
                is_public BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_site_settings_key (`key`),
                INDEX idx_site_settings_category (category),
                INDEX idx_site_settings_public (is_public)
            )
        """

        return self.execute_sql(sql, description="Created site_settings table")

    def migration_015_create_email_tables(self) -> bool:
        """Міграція 015: Створює таблиці для email системи."""
        success = True

        # Таблиця email шаблонів
        if not self.table_exists('email_templates'):
            sql = """
                CREATE TABLE email_templates (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    subject_uk VARCHAR(255) NOT NULL,
                    subject_en VARCHAR(255) NOT NULL,
                    content_uk TEXT NOT NULL,
                    content_en TEXT NOT NULL,
                    variables JSON,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_email_templates_name (name),
                    INDEX idx_email_templates_active (is_active)
                )
            """
            if not self.execute_sql(sql, description="Created email_templates table"):
                success = False

        # Таблиця логів email
        if not self.table_exists('email_logs'):
            sql = """
                CREATE TABLE email_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    template_name VARCHAR(100),
                    recipient_email VARCHAR(255) NOT NULL,
                    subject VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    error_message TEXT,
                    sent_at TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_email_logs_recipient (recipient_email),
                    INDEX idx_email_logs_status (status),
                    INDEX idx_email_logs_template (template_name),
                    INDEX idx_email_logs_created (created_at)
                )
            """
            if not self.execute_sql(sql, description="Created email_logs table"):
                success = False

        return success

    def migration_016_create_site_stats_table(self) -> bool:
        """Міграція 016: Створює таблицю для статистики сайту."""
        if self.table_exists('site_stats'):
            return True

        sql = """
            CREATE TABLE site_stats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                date DATETIME NOT NULL,
                visits INT DEFAULT 0,
                page_views INT DEFAULT 0,
                unique_visitors INT DEFAULT 0,
                quote_applications INT DEFAULT 0,
                consultation_applications INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE INDEX idx_site_stats_date (date),
                INDEX idx_site_stats_date_range (date, visits)
            )
        """

        return self.execute_sql(sql, description="Created site_stats table")

    def migration_017_add_category_active_field(self) -> bool:
        """Міграція 017: Додає поле is_active до таблиці design_categories."""
        if not self.table_exists('design_categories'):
            return True

        if self.column_exists('design_categories', 'is_active'):
            return True

        sql = "ALTER TABLE design_categories ADD COLUMN is_active BOOLEAN DEFAULT TRUE"
        return self.execute_sql(sql, description="Added is_active to design_categories")

    def migration_018_optimize_database_settings(self) -> bool:
        """Міграція 018: Оптимізує налаштування бази даних."""
        optimizations = [
            ("SET GLOBAL innodb_buffer_pool_size = 134217728", "Set InnoDB buffer pool size"),  # 128MB
            ("SET GLOBAL query_cache_size = 16777216", "Set query cache size"),  # 16MB
            ("SET GLOBAL max_connections = 151", "Set max connections"),
        ]

        success_count = 0
        for sql, description in optimizations:
            try:
                if not self.dry_run:
                    with self.engine.connect() as connection:
                        connection.execute(text(sql))
                    logger.info(f"✅ {description}")
                else:
                    logger.info(f"[DRY RUN] Would execute: {description}")
                success_count += 1
            except Exception as e:
                logger.warning(f"⚠️  {description} failed: {e}")

        return success_count > 0

    def run_migration(self, migration: Migration) -> bool:
        """Виконує одну міграцію."""
        method_name = f"migration_{migration.version}_{migration.name}"

        if not hasattr(self, method_name):
            logger.error(f"Migration method {method_name} not found")
            return False

        start_time = datetime.now()

        try:
            logger.info(f"🔄 Running migration {migration.version}: {migration.description}")

            method = getattr(self, method_name)
            success = method()

            end_time = datetime.now()
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            migration.success = success
            migration.executed_at = end_time

            if success:
                logger.info(f"✅ Migration {migration.version} completed successfully in {execution_time_ms}ms")
                if not self.dry_run:
                    self.record_migration(migration, execution_time_ms)
            else:
                logger.error(f"❌ Migration {migration.version} failed")
                migration.error_message = "Migration method returned False"
                if not self.dry_run:
                    self.record_migration(migration, execution_time_ms)

            return success

        except Exception as e:
            end_time = datetime.now()
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            migration.success = False
            migration.error_message = str(e)
            migration.executed_at = end_time

            logger.error(f"❌ Migration {migration.version} failed with error: {e}")

            if not self.dry_run:
                self.record_migration(migration, execution_time_ms)

            return False

    def run_all_migrations(self, target_version: Optional[str] = None) -> bool:
        """Запускає всі міграції до вказаної версії."""
        logger.info("🚀 Starting database migrations...")

        if self.dry_run:
            logger.info("🧪 Running in DRY RUN mode - no changes will be made")

        migrations = self.get_migration_definitions()
        executed_migrations = self.get_executed_migrations()

        # Фільтруємо міграції
        pending_migrations = []
        for migration in migrations:
            if migration.version not in executed_migrations:
                pending_migrations.append(migration)
                if target_version and migration.version == target_version:
                    break

        if not pending_migrations:
            logger.info("✅ No pending migrations found")
            return True

        logger.info(f"📋 Found {len(pending_migrations)} pending migrations")

        successful_migrations = 0
        failed_migrations = []

        for migration in pending_migrations:
            if self.run_migration(migration):
                successful_migrations += 1
            else:
                failed_migrations.append(migration)
                # Зупиняємось на першій помилці
                break

        # Підсумок
        logger.info("=" * 50)
        logger.info(f"📊 Migration Summary:")
        logger.info(f"   ✅ Successful: {successful_migrations}")
        logger.info(f"   ❌ Failed: {len(failed_migrations)}")
        logger.info(f"   📝 Total processed: {successful_migrations + len(failed_migrations)}")

        if failed_migrations:
            logger.error("❌ Migration process failed!")
            for migration in failed_migrations:
                logger.error(f"   - {migration.version}: {migration.error_message}")
            return False

        logger.info("🎉 All migrations completed successfully!")
        return True

    def get_migration_status(self) -> Dict[str, Any]:
        """Отримує статус міграцій."""
        try:
            all_migrations = self.get_migration_definitions()
            executed_migrations = self.get_executed_migrations()

            status = {
                "total_migrations": len(all_migrations),
                "executed_migrations": len(executed_migrations),
                "pending_migrations": len(all_migrations) - len(executed_migrations),
                "migrations": []
            }

            for migration in all_migrations:
                migration_info = {
                    "version": migration.version,
                    "name": migration.name,
                    "description": migration.description,
                    "executed": migration.version in executed_migrations
                }
                status["migrations"].append(migration_info)

            return status

        except Exception as e:
            logger.error(f"Failed to get migration status: {e}")
            return {"error": str(e)}

    def rollback_migration(self, version: str) -> bool:
        """Відкочує міграцію (якщо можливо)."""
        logger.warning("⚠️  Migration rollback is not implemented yet")
        logger.info("💡 For now, you need to manually revert database changes")
        return False


def main():
    """Головна функція скрипта."""
    parser = argparse.ArgumentParser(description="WebCraft Pro Database Migration Tool")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be executed without making changes")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--target", help="Target migration version")
    parser.add_argument("--rollback", help="Rollback to specific version")
    parser.add_argument("--force", action="store_true", help="Force execution even if risky")

    args = parser.parse_args()

    print("WebCraft Pro Database Migration Tool")
    print("=" * 50)

    try:
        with DatabaseMigrator(dry_run=args.dry_run) as migrator:
            if args.status:
                # Показуємо статус міграцій
                status = migrator.get_migration_status()

                print(f"📊 Migration Status:")
                print(f"   Total migrations: {status['total_migrations']}")
                print(f"   Executed: {status['executed_migrations']}")
                print(f"   Pending: {status['pending_migrations']}")
                print()

                for migration in status["migrations"]:
                    status_icon = "✅" if migration["executed"] else "⏳"
                    print(f"   {status_icon} {migration['version']}: {migration['name']}")

                return

            elif args.rollback:
                # Відкочуємо міграцію
                success = migrator.rollback_migration(args.rollback)
                sys.exit(0 if success else 1)

            else:
                # Запускаємо міграції
                success = migrator.run_all_migrations(target_version=args.target)

                if success:
                    print("🎉 All migrations completed successfully!")

                    # Показуємо статистику БД
                    try:
                        stats = get_database_stats()
                        print(f"\n📊 Database Statistics:")
                        for key, value in stats.items():
                            if isinstance(value, (int, dict)) and key != "error":
                                print(f"   {key}: {value}")
                    except:
                        pass

                    sys.exit(0)
                else:
                    print("❌ Migration process failed!")
                    sys.exit(1)

    except KeyboardInterrupt:
        print("\n👋 Migration cancelled by user")
        sys.exit(1)

    except Exception as e:
        logger.error(f"❌ Fatal error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()