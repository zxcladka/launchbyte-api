from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, JSON, Index, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum


# Енумы для статусов
class ApplicationStatus(str, enum.Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ContentType(str, enum.Enum):
    HERO = "hero"
    ABOUT = "about"
    SERVICES = "services"
    CONTACTS = "contacts"
    PRIVACY_POLICY = "privacy_policy"
    TERMS_OF_USE = "terms_of_use"


class SettingsCategory(str, enum.Enum):
    GENERAL = "general"
    SEO = "seo"
    BRANDING = "branding"
    SMTP = "smtp"
    ANALYTICS = "analytics"
    FEATURES = "features"


# Пользователи
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    avatar_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Зв'язки - ИСПРАВЛЕНО: указываем foreign_keys
    reviews = relationship("Review", back_populates="user", foreign_keys="Review.user_id", cascade="all, delete-orphan")
    quote_applications = relationship("QuoteApplication", back_populates="user", foreign_keys="QuoteApplication.user_id", cascade="all, delete-orphan")
    consultation_applications = relationship("ConsultationApplication", back_populates="user", foreign_keys="ConsultationApplication.user_id", cascade="all, delete-orphan")
    uploaded_files = relationship("UploadedFile", back_populates="uploaded_by", cascade="all, delete-orphan")


# Категории дизайнов
class DesignCategory(Base):
    __tablename__ = "design_categories"

    id = Column(String(50), primary_key=True)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    title_uk = Column(String(255), nullable=False)
    title_en = Column(String(255), nullable=False)
    description_uk = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Зв'язки
    designs = relationship("Design", back_populates="category_rel", cascade="all, delete-orphan")


# Дизайны
class Design(Base):
    __tablename__ = "designs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=True)

    # Многоязычный контент
    title_uk = Column(String(255), nullable=False)
    title_en = Column(String(255), nullable=False)
    description_uk = Column(Text, nullable=False)
    description_en = Column(Text, nullable=False)
    metrics_uk = Column(Text, nullable=True)
    metrics_en = Column(Text, nullable=True)

    # Техническая информация
    category_id = Column(String(50), ForeignKey("design_categories.id"), nullable=False, index=True)
    technology = Column(String(255), nullable=False)
    image_url = Column(String(500), nullable=False)
    figma_url = Column(String(500), nullable=True)
    live_url = Column(String(500), nullable=True)
    show_live_demo = Column(Boolean, default=True)

    # SEO
    meta_title_uk = Column(String(255), nullable=True)
    meta_title_en = Column(String(255), nullable=True)
    meta_description_uk = Column(Text, nullable=True)
    meta_description_en = Column(Text, nullable=True)

    # Статус
    is_published = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    views_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Зв'язки
    category_rel = relationship("DesignCategory", back_populates="designs")

    # Індекси для покращення продуктивності
    __table_args__ = (
        Index('idx_design_category_published', 'category_id', 'is_published'),
        Index('idx_design_featured_published', 'is_featured', 'is_published'),
    )


# Пакети послуг
class Package(Base):
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=True)

    # Ценообразование
    price_uk = Column(String(255), nullable=False)  # "від €1 500"
    price_en = Column(String(255), nullable=False)  # "from €1,500"
    duration_uk = Column(String(255), nullable=False)
    duration_en = Column(String(255), nullable=False)

    # Контент - хранится как JSON
    features_uk = Column(JSON, nullable=False)  # список строк
    features_en = Column(JSON, nullable=False)
    advantages_uk = Column(JSON, nullable=True)
    advantages_en = Column(JSON, nullable=True)
    process_uk = Column(JSON, nullable=True)
    process_en = Column(JSON, nullable=True)
    support_uk = Column(Text, nullable=True)
    support_en = Column(Text, nullable=True)

    # Настройки
    is_popular = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    # SEO
    meta_title_uk = Column(String(255), nullable=True)
    meta_title_en = Column(String(255), nullable=True)
    meta_description_uk = Column(Text, nullable=True)
    meta_description_en = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Зв'язки
    quote_applications = relationship("QuoteApplication", back_populates="package")


# Відгуки
class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # может быть анонимным

    # Контент отзыва
    text_uk = Column(Text, nullable=False)
    text_en = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    company = Column(String(255), nullable=True)

    # Контактная информация (если пользователь анонимный)
    author_name = Column(String(255), nullable=True)  # если user_id = NULL
    author_email = Column(String(255), nullable=True)  # если user_id = NULL

    # Модерация
    is_approved = Column(Boolean, default=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # SEO и отображение
    is_featured = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Зв'язки - ИСПРАВЛЕНО: правильно указываем foreign_keys
    user = relationship("User", back_populates="reviews", foreign_keys=[user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])

    # Індекси
    __table_args__ = (
        Index('idx_review_approved_featured', 'is_approved', 'is_featured'),
        Index('idx_review_user_approved', 'user_id', 'is_approved'),
    )


# FAQ
class FAQ(Base):
    __tablename__ = "faq"

    id = Column(Integer, primary_key=True, index=True)

    # Контент
    question_uk = Column(String(500), nullable=False)
    question_en = Column(String(500), nullable=False)
    answer_uk = Column(Text, nullable=False)
    answer_en = Column(Text, nullable=False)

    # Настройки
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0, index=True)

    # SEO
    slug_uk = Column(String(255), nullable=True, index=True)
    slug_en = Column(String(255), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Заявки на прорахунок
class QuoteApplication(Base):
    __tablename__ = "quote_applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Контактные данные
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(255), nullable=True)

    # Проект
    project_type = Column(String(255), nullable=False)
    budget = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)

    # Связанный пакет (если выбран)
    package_id = Column(Integer, ForeignKey("packages.id"), nullable=True, index=True)

    # Статус и обработка
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.NEW, index=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    response_text = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Зв'язки - ИСПРАВЛЕНО: указываем foreign_keys для устранения неоднозначности
    user = relationship("User", back_populates="quote_applications", foreign_keys=[user_id])
    package = relationship("Package", back_populates="quote_applications")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])


# Заявки на консультацию
class ConsultationApplication(Base):
    __tablename__ = "consultation_applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Контактные данные
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    phone = Column(String(255), nullable=False)
    telegram = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)

    # Статус и обработка
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.NEW, index=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    consultation_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    consultation_completed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Зв'язки - ИСПРАВЛЕНО: указываем foreign_keys для устранения неоднозначности
    user = relationship("User", back_populates="consultation_applications", foreign_keys=[user_id])
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])


# Управление контентом
class Content(Base):
    __tablename__ = "content"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ContentType), nullable=True)
    key = Column(String(255), nullable=False)  # hero.title1, about.mission

    # Многоязычный контент
    content_uk = Column(Text, nullable=True)
    content_en = Column(Text, nullable=True)

    # Метаданные
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # Уникальная комбинация type + key
        Index("ix_content_key", "key", unique=True),
    )


# Настройки сайта
class SiteSettings(Base):
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(Enum(SettingsCategory), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=True)
    type = Column(String(50), default="string")

    # Метаданные
    description = Column(String(500), nullable=True)
    is_public = Column(Boolean, default=False)  # Доступно через API

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_settings_category_key", "category", "key", unique=True),
    )


# Файловый менеджер
class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Информация о файле
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=False)

    # Метаданные
    file_size = Column(Integer, nullable=False)  # в байтах
    mime_type = Column(String(255), nullable=False)
    file_extension = Column(String(20), nullable=False)

    # Категоризация
    folder = Column(String(100), nullable=True)  # designs, logos, documents
    alt_text = Column(String(255), nullable=True)

    # Дополнительные поля
    thumbnail_url = Column(String(500), nullable=True)
    category = Column(String(50), default="other", index=True)
    hash = Column(String(64), nullable=True, index=True)

    # Статус
    is_used = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Зв'язки
    uploaded_by = relationship("User", back_populates="uploaded_files")


# Контактная информация
class ContactInfo(Base):
    __tablename__ = "contact_info"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    telegram = Column(String(255), nullable=True)
    telegram_url = Column(String(500), nullable=True)
    address_uk = Column(String(500), nullable=True)
    address_en = Column(String(500), nullable=True)
    working_hours_uk = Column(String(255), nullable=True)
    working_hours_en = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# SEO настройки
class SEOSettings(Base):
    __tablename__ = "seo_settings"

    id = Column(Integer, primary_key=True, index=True)
    page = Column(String(255), nullable=False, default="home", unique=True, index=True)
    meta_title_uk = Column(String(255), nullable=True)
    meta_title_en = Column(String(255), nullable=True)
    meta_description_uk = Column(Text, nullable=True)
    meta_description_en = Column(Text, nullable=True)
    meta_keywords_uk = Column(Text, nullable=True)
    meta_keywords_en = Column(Text, nullable=True)
    og_title_uk = Column(String(255), nullable=True)
    og_title_en = Column(String(255), nullable=True)
    og_description_uk = Column(Text, nullable=True)
    og_description_en = Column(Text, nullable=True)
    og_image = Column(String(500), nullable=True)
    favicon = Column(String(500), nullable=True)
    structured_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Политики
class Policy(Base):
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), unique=True, nullable=False, index=True)
    title_uk = Column(String(255), nullable=True)
    title_en = Column(String(255), nullable=True)
    content_uk = Column(Text, nullable=True)
    content_en = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    version = Column(String(50), default="1.0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Статистика сайта
class SiteStats(Base):
    __tablename__ = "site_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    visits = Column(Integer, default=0)
    page_views = Column(Integer, default=0)
    unique_visitors = Column(Integer, default=0)
    quote_applications = Column(Integer, default=0)
    consultation_applications = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Уникальный индекс по дате
    __table_args__ = (
        Index('idx_site_stats_date', 'date', unique=True),
    )


# Email шаблоны
class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    subject_uk = Column(String(255), nullable=False)
    subject_en = Column(String(255), nullable=False)
    content_uk = Column(Text, nullable=False)
    content_en = Column(Text, nullable=False)
    variables = Column(JSON, nullable=True)  # Список доступных переменных
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Логи email отправок
class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    template_name = Column(String(100), nullable=True, index=True)
    recipient_email = Column(String(255), nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(50), default="pending", index=True)  # pending, sent, failed
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Індекси для пошуку
    __table_args__ = (
        Index('idx_email_log_status_date', 'status', 'created_at'),
    )