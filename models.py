from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, JSON, Index, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum


# ============ ЕНУМЫ ============

class ApplicationStatus(str, enum.Enum):
    """Статусы заявок"""
    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ContentType(str, enum.Enum):
    """Типы контента"""
    HERO = "hero"
    ABOUT = "about"
    SERVICES = "services"
    CONTACTS = "contacts"
    PRIVACY_POLICY = "privacy_policy"
    TERMS_OF_USE = "terms_of_use"


class SettingsCategory(str, enum.Enum):
    """Категории настроек сайта"""
    GENERAL = "general"
    SEO = "seo"
    BRANDING = "branding"
    SMTP = "smtp"
    ANALYTICS = "analytics"
    FEATURES = "features"


class EmailStatus(str, enum.Enum):
    """Статусы email отправки"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRY = "retry"


class FileCategory(str, enum.Enum):
    """Категории файлов"""
    IMAGES = "images"
    DOCUMENTS = "documents"
    MEDIA = "media"
    OTHER = "other"


# ============ ОСНОВНЫЕ МОДЕЛИ ============

class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, index=True)
    is_active = Column(Boolean, default=True, index=True)
    avatar_url = Column(String(500), nullable=True)

    # НОВЫЕ ПОЛЯ для v2.0
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    last_login = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ИСПРАВЛЕННЫЕ relationships
    reviews = relationship(
        "Review",
        primaryjoin="User.id == Review.user_id",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    quote_applications = relationship(
        "QuoteApplication",
        primaryjoin="User.id == QuoteApplication.user_id",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    consultation_applications = relationship(
        "ConsultationApplication",
        primaryjoin="User.id == ConsultationApplication.user_id",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    uploaded_files = relationship(
        "UploadedFile",
        back_populates="uploaded_by",
        cascade="all, delete-orphan"
    )

    # Индексы для оптимизации
    __table_args__ = (
        Index('idx_user_email_active', 'email', 'is_active'),
        Index('idx_user_admin_active', 'is_admin', 'is_active'),
    )


class DesignCategory(Base):
    """Категории дизайнов"""
    __tablename__ = "design_categories"

    id = Column(String(50), primary_key=True)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    title_uk = Column(String(255), nullable=False)
    title_en = Column(String(255), nullable=False)
    description_uk = Column(Text, nullable=True)
    description_en = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    designs = relationship("Design", back_populates="category_rel", cascade="all, delete-orphan")

    # Индексы
    __table_args__ = (
        Index('idx_category_active_order', 'is_active', 'sort_order'),
    )


class Design(Base):
    """Дизайны портфолио"""
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

    # Статус и отображение
    is_published = Column(Boolean, default=True, index=True)
    is_featured = Column(Boolean, default=False, index=True)
    sort_order = Column(Integer, default=0, index=True)
    views_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    category_rel = relationship("DesignCategory", back_populates="designs")

    # Индексы для производительности
    __table_args__ = (
        Index('idx_design_category_published', 'category_id', 'is_published'),
        Index('idx_design_featured_published', 'is_featured', 'is_published'),
        Index('idx_design_published_order', 'is_published', 'sort_order'),
    )


class Package(Base):
    """Пакеты услуг"""
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=True)

    # Ценообразование
    price_uk = Column(String(255), nullable=False)  # "від €1 500"
    price_en = Column(String(255), nullable=False)  # "from €1,500"
    duration_uk = Column(String(255), nullable=False)
    duration_en = Column(String(255), nullable=False)

    # Контент - хранится как JSON массив строк
    features_uk = Column(JSON, nullable=False)
    features_en = Column(JSON, nullable=False)
    advantages_uk = Column(JSON, nullable=True)
    advantages_en = Column(JSON, nullable=True)
    process_uk = Column(JSON, nullable=True)
    process_en = Column(JSON, nullable=True)
    support_uk = Column(Text, nullable=True)
    support_en = Column(Text, nullable=True)

    # Настройки
    is_popular = Column(Boolean, default=False, index=True)
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0, index=True)

    # SEO
    meta_title_uk = Column(String(255), nullable=True)
    meta_title_en = Column(String(255), nullable=True)
    meta_description_uk = Column(Text, nullable=True)
    meta_description_en = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    quote_applications = relationship("QuoteApplication", back_populates="package")

    # Индексы
    __table_args__ = (
        Index('idx_package_active_popular', 'is_active', 'is_popular'),
        Index('idx_package_active_order', 'is_active', 'sort_order'),
    )


# ============ НОВЫЕ МОДЕЛИ V2.0 ============

class AboutContent(Base):
    """НОВАЯ МОДЕЛЬ: Контент страницы 'О нас'"""
    __tablename__ = "about_content"

    id = Column(Integer, primary_key=True, index=True)

    # Hero секция
    hero_description_uk = Column(Text, nullable=True)
    hero_description_en = Column(Text, nullable=True)

    # Миссия и видение
    mission_uk = Column(Text, nullable=True)
    mission_en = Column(Text, nullable=True)
    vision_uk = Column(Text, nullable=True)
    vision_en = Column(Text, nullable=True)

    # Почему выбирают нас
    why_choose_us_uk = Column(Text, nullable=True)
    why_choose_us_en = Column(Text, nullable=True)

    # Call to Action
    cta_title_uk = Column(String(255), nullable=True)
    cta_title_en = Column(String(255), nullable=True)
    cta_description_uk = Column(Text, nullable=True)
    cta_description_en = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TeamMember(Base):
    """НОВАЯ МОДЕЛЬ: Члены команды"""
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)

    # Роли на двух языках
    role_uk = Column(String(255), nullable=False)
    role_en = Column(String(255), nullable=False)

    # Навыки (строка через запятую или JSON)
    skills = Column(Text, nullable=True)

    # Аватар и инициалы
    avatar = Column(String(500), nullable=True)
    initials = Column(String(3), nullable=False)

    # Сортировка и статус
    order_index = Column(Integer, default=0, index=True)
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Индексы для быстрого поиска активных членов команды
    __table_args__ = (
        Index('idx_team_active_order', 'is_active', 'order_index'),
        Index('idx_team_name_active', 'name', 'is_active'),
    )


# ============ ОТЗЫВЫ И ОБРАТНАЯ СВЯЗЬ ============

class Review(Base):
    """Отзывы клиентов"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Контент отзыва
    text_uk = Column(Text, nullable=False)
    text_en = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 звезд
    company = Column(String(255), nullable=True)

    # Для анонимных отзывов
    author_name = Column(String(255), nullable=True)
    author_email = Column(String(255), nullable=True)

    # Модерация
    is_approved = Column(Boolean, default=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Отображение
    is_featured = Column(Boolean, default=False, index=True)
    sort_order = Column(Integer, default=0, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    user = relationship("User", primaryjoin="User.id == Review.user_id", back_populates="reviews")
    approved_by = relationship("User", primaryjoin="User.id == Review.approved_by_id")

    # Индексы
    __table_args__ = (
        Index('idx_review_approved_featured', 'is_approved', 'is_featured'),
        Index('idx_review_approved_order', 'is_approved', 'sort_order'),
        Index('idx_review_rating', 'rating'),
    )


class FAQ(Base):
    """Часто задаваемые вопросы"""
    __tablename__ = "faq"

    id = Column(Integer, primary_key=True, index=True)

    # Контент
    question_uk = Column(String(500), nullable=False)
    question_en = Column(String(500), nullable=False)
    answer_uk = Column(Text, nullable=False)
    answer_en = Column(Text, nullable=False)

    # Настройки
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0, index=True)

    # SEO
    slug_uk = Column(String(255), nullable=True, index=True)
    slug_en = Column(String(255), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Индексы
    __table_args__ = (
        Index('idx_faq_active_order', 'is_active', 'sort_order'),
    )


# ============ ЗАЯВКИ ============

class QuoteApplication(Base):
    """Заявки на расчет проектов"""
    __tablename__ = "quote_applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Контактные данные
    name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(255), nullable=True)

    # Проект
    project_type = Column(String(255), nullable=False)
    budget = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)

    # Связанный пакет
    package_id = Column(Integer, ForeignKey("packages.id"), nullable=True, index=True)

    # Статус и обработка
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.NEW, index=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    response_text = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    user = relationship("User", primaryjoin="User.id == QuoteApplication.user_id", back_populates="quote_applications")
    package = relationship("Package", back_populates="quote_applications")
    assigned_to = relationship("User", primaryjoin="User.id == QuoteApplication.assigned_to_id")

    # Индексы
    __table_args__ = (
        Index('idx_quote_status_created', 'status', 'created_at'),
        Index('idx_quote_email_status', 'email', 'status'),
    )


class ConsultationApplication(Base):
    """Заявки на консультации"""
    __tablename__ = "consultation_applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Контактные данные
    first_name = Column(String(255), nullable=False, index=True)
    last_name = Column(String(255), nullable=False, index=True)
    phone = Column(String(255), nullable=False, index=True)
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

    # Связи
    user = relationship("User", primaryjoin="User.id == ConsultationApplication.user_id",
                        back_populates="consultation_applications")
    assigned_to = relationship("User", primaryjoin="User.id == ConsultationApplication.assigned_to_id")

    # Индексы
    __table_args__ = (
        Index('idx_consultation_status_created', 'status', 'created_at'),
        Index('idx_consultation_name', 'first_name', 'last_name'),
    )


# ============ КОНТЕНТ И НАСТРОЙКИ ============

class Content(Base):
    """Управление контентом сайта"""
    __tablename__ = "content"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ContentType), nullable=True, index=True)
    key = Column(String(255), nullable=False, unique=True, index=True)

    # Многоязычный контент
    content_uk = Column(Text, nullable=True)
    content_en = Column(Text, nullable=True)

    # Метаданные
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Индексы
    __table_args__ = (
        Index('idx_content_type_active', 'type', 'is_active'),
    )


class SiteSettings(Base):
    """Настройки сайта"""
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(Enum(SettingsCategory), nullable=False, index=True)
    key = Column(String(255), nullable=False, index=True)
    value = Column(Text, nullable=True)
    type = Column(String(50), default="string")

    # Метаданные
    description = Column(String(500), nullable=True)
    is_public = Column(Boolean, default=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Уникальная комбинация категории и ключа
    __table_args__ = (
        Index("idx_settings_category_key", "category", "key", unique=True),
        Index("idx_settings_public", "is_public", "category"),
    )


class ContactInfo(Base):
    """Контактная информация"""
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


class SEOSettings(Base):
    """SEO настройки для страниц"""
    __tablename__ = "seo_settings"

    id = Column(Integer, primary_key=True, index=True)
    page = Column(String(255), nullable=False, unique=True, index=True)

    # Метатеги
    meta_title_uk = Column(String(255), nullable=True)
    meta_title_en = Column(String(255), nullable=True)
    meta_description_uk = Column(Text, nullable=True)
    meta_description_en = Column(Text, nullable=True)
    meta_keywords_uk = Column(Text, nullable=True)
    meta_keywords_en = Column(Text, nullable=True)

    # Open Graph
    og_title_uk = Column(String(255), nullable=True)
    og_title_en = Column(String(255), nullable=True)
    og_description_uk = Column(Text, nullable=True)
    og_description_en = Column(Text, nullable=True)
    og_image = Column(String(500), nullable=True)

    # Дополнительные настройки
    favicon = Column(String(500), nullable=True)
    structured_data = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Policy(Base):
    """Политики и юридические документы"""
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), unique=True, nullable=False, index=True)
    title_uk = Column(String(255), nullable=True)
    title_en = Column(String(255), nullable=True)
    content_uk = Column(Text, nullable=True)
    content_en = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    version = Column(String(50), default="1.0")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Индексы
    __table_args__ = (
        Index('idx_policy_type_active', 'type', 'is_active'),
    )


# ============ ФАЙЛЫ ============

class UploadedFile(Base):
    """Файловый менеджер"""
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Информация о файле
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=False)

    # Метаданные файла
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(255), nullable=False)
    file_extension = Column(String(20), nullable=False, index=True)

    # Категоризация и дополнительные данные
    folder = Column(String(100), nullable=True, index=True)
    category = Column(String(50), default="other", index=True)
    alt_text = Column(String(255), nullable=True)
    hash = Column(String(64), nullable=True, index=True)

    # Дополнительные поля для изображений
    thumbnail_url = Column(String(500), nullable=True)
    is_used = Column(Boolean, default=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    uploaded_by = relationship("User", back_populates="uploaded_files")

    # Индексы
    __table_args__ = (
        Index('idx_file_category_used', 'category', 'is_used'),
        Index('idx_file_extension_category', 'file_extension', 'category'),
        Index('idx_file_created', 'created_at'),
    )


# ============ EMAIL СИСТЕМА ============

class EmailTemplate(Base):
    """Шаблоны email сообщений"""
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)

    # Контент шаблона
    subject_uk = Column(String(255), nullable=False)
    subject_en = Column(String(255), nullable=False)
    content_uk = Column(Text, nullable=False)
    content_en = Column(Text, nullable=False)

    # Переменные шаблона
    variables = Column(JSON, nullable=True)  # массив доступных переменных

    # Настройки
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи с логами
    email_logs = relationship("EmailLog", back_populates="template")


class EmailLog(Base):
    """Логи отправки email сообщений"""
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    template_name = Column(String(100), ForeignKey("email_templates.name"), nullable=True, index=True)

    # Данные отправки
    recipient_email = Column(String(255), nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)

    # Статус отправки
    status = Column(Enum(EmailStatus), default=EmailStatus.PENDING, index=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # Временные метки
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    template = relationship("EmailTemplate", back_populates="email_logs")

    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_email_log_status_created', 'status', 'created_at'),
        Index('idx_email_log_recipient_status', 'recipient_email', 'status'),
        Index('idx_email_log_template_status', 'template_name', 'status'),
    )


# ============ СТАТИСТИКА И АНАЛИТИКА ============

class SiteStats(Base):
    """Статистика посещений сайта"""
    __tablename__ = "site_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)

    # Метрики посещений
    visits = Column(Integer, default=0)
    page_views = Column(Integer, default=0)
    unique_visitors = Column(Integer, default=0)

    # Метрики конверсии
    quote_applications = Column(Integer, default=0)
    consultation_applications = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Уникальный индекс по дате
    __table_args__ = (
        Index('idx_site_stats_date_unique', 'date', unique=True),
    )


# ============ БЕЗОПАСНОСТЬ И МОНИТОРИНГ ============

class SecurityEvent(Base):
    """Логи событий безопасности (новая модель для v2.0)"""
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Тип события
    event_type = Column(String(100), nullable=False, index=True)  # login_failed, password_change, etc.
    severity = Column(String(20), default="medium", index=True)  # low, medium, high, critical

    # Детали события
    ip_address = Column(String(45), nullable=False, index=True)
    user_agent = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)

    # Статус обработки
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    user = relationship("User", primaryjoin="User.id == SecurityEvent.user_id")
    resolved_by = relationship("User", primaryjoin="User.id == SecurityEvent.resolved_by_id")

    # Индексы для мониторинга
    __table_args__ = (
        Index('idx_security_type_severity', 'event_type', 'severity'),
        Index('idx_security_unresolved', 'resolved', 'created_at'),
        Index('idx_security_ip_created', 'ip_address', 'created_at'),
    )


class AdminActivityLog(Base):
    """Логи действий администраторов (новая модель для v2.0)"""
    __tablename__ = "admin_activity_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Действие
    action = Column(String(100), nullable=False, index=True)  # create, update, delete
    resource_type = Column(String(50), nullable=False, index=True)  # team_member, about_content, etc.
    resource_id = Column(Integer, nullable=True, index=True)

    # Детали действия
    details = Column(JSON, nullable=True)  # измененные поля, старые значения
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    user = relationship("User")

    # Индексы для аудита
    __table_args__ = (
        Index('idx_admin_activity_user_action', 'user_id', 'action'),
        Index('idx_admin_activity_resource', 'resource_type', 'resource_id'),
        Index('idx_admin_activity_created', 'created_at'),
    )