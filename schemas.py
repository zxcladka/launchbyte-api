from pydantic import BaseModel, EmailStr, validator, Field, HttpUrl
from typing import Optional, List, Union, Dict, Any
from datetime import datetime
from enum import Enum
import re


# Базові схеми
class BaseSchema(BaseModel):
    class Config:
        from_attributes = True
        str_strip_whitespace = True


# Статуси заявок
class ApplicationStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Email шаблони статуси
class EmailStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


# Типи файлів
class FileCategory(str, Enum):
    IMAGES = "images"
    DOCUMENTS = "documents"
    MEDIA = "media"
    OTHER = "other"


# Content types
class ContentType(str, Enum):
    HERO = "hero"
    ABOUT = "about"
    SERVICES = "services"
    CONTACTS = "contacts"
    PRIVACY_POLICY = "privacy_policy"
    TERMS_OF_USE = "terms_of_use"


# ============ СХЕМИ КОРИСТУВАЧІВ ============

class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=100)

    @validator('name')
    def validate_name(cls, v):
        if not v or v.isspace():
            raise ValueError('Name cannot be empty')
        # Прибираємо зайві пробіли
        return ' '.join(v.split())


class UserCreate(UserBase):
    password: str = Field(min_length=6, max_length=100)

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    avatar_url: Optional[str] = None


class UserResponse(UserBase):
    id: int
    is_admin: bool = False
    is_active: bool = True
    avatar_url: Optional[str] = None
    password_changed_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# НОВАЯ СХЕМА: Смена пароля
class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)

    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 6:
            raise ValueError('New password must be at least 6 characters long')
        return v


class PasswordChangeResponse(BaseModel):
    message: str
    changed_at: datetime


# ============ СХЕМИ ДИЗАЙНІВ ============

class DesignCategoryBase(BaseModel):
    title_uk: str = Field(min_length=1, max_length=255)
    title_en: str = Field(min_length=1, max_length=255)
    description_uk: Optional[str] = None
    description_en: Optional[str] = None


class DesignCategoryCreate(DesignCategoryBase):
    id: str = Field(min_length=1, max_length=50)
    slug: str = Field(min_length=1, max_length=255)

    @validator('id', 'slug')
    def validate_slug_format(cls, v):
        # Тільки латинські літери, цифри, дефіси та підкреслення
        if not re.match(r'^[a-z0-9_-]+$', v.lower()):
            raise ValueError('Slug must contain only lowercase letters, numbers, hyphens and underscores')
        return v.lower()


class DesignCategoryUpdate(BaseModel):
    title_uk: Optional[str] = Field(None, min_length=1, max_length=255)
    title_en: Optional[str] = Field(None, min_length=1, max_length=255)
    description_uk: Optional[str] = None
    description_en: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class DesignCategory(DesignCategoryBase):
    id: str
    slug: str
    is_active: bool = True
    sort_order: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class DesignBase(BaseModel):
    title: str = Field(min_length=5, max_length=255)
    title_uk: str = Field(min_length=5, max_length=255)
    title_en: str = Field(min_length=5, max_length=255)
    category_id: str = Field(min_length=1, max_length=50)
    technology: str = Field(min_length=1, max_length=255)
    description_uk: str = Field(min_length=50, max_length=2000)
    description_en: str = Field(min_length=50, max_length=2000)
    image_url: str = Field(min_length=1, max_length=500)
    figma_url: Optional[str] = Field(None, max_length=500)
    live_url: Optional[str] = Field(None, max_length=500)
    show_live_demo: bool = True
    metrics_uk: Optional[str] = Field(None, max_length=500)
    metrics_en: Optional[str] = Field(None, max_length=500)

    @validator('figma_url', 'live_url')
    def validate_urls(cls, v):
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError('URL must be a valid URL starting with http:// or https://')
        return v


class DesignCreate(DesignBase):
    is_featured: bool = False
    sort_order: int = 0
    meta_title_uk: Optional[str] = Field(None, max_length=255)
    meta_title_en: Optional[str] = Field(None, max_length=255)
    meta_description_uk: Optional[str] = Field(None, max_length=320)
    meta_description_en: Optional[str] = Field(None, max_length=320)


class DesignUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=5, max_length=255)
    title_uk: Optional[str] = Field(None, min_length=5, max_length=255)
    title_en: Optional[str] = Field(None, min_length=5, max_length=255)
    category_id: Optional[str] = Field(None, min_length=1, max_length=50)
    technology: Optional[str] = Field(None, min_length=1, max_length=255)
    description_uk: Optional[str] = Field(None, min_length=50, max_length=2000)
    description_en: Optional[str] = Field(None, min_length=50, max_length=2000)
    image_url: Optional[str] = Field(None, min_length=1, max_length=500)
    figma_url: Optional[str] = Field(None, max_length=500)
    live_url: Optional[str] = Field(None, max_length=500)
    show_live_demo: Optional[bool] = None
    metrics_uk: Optional[str] = Field(None, max_length=500)
    metrics_en: Optional[str] = Field(None, max_length=500)
    is_published: Optional[bool] = None
    is_featured: Optional[bool] = None
    sort_order: Optional[int] = None
    meta_title_uk: Optional[str] = Field(None, max_length=255)
    meta_title_en: Optional[str] = Field(None, max_length=255)
    meta_description_uk: Optional[str] = Field(None, max_length=320)
    meta_description_en: Optional[str] = Field(None, max_length=320)


class Design(DesignBase):
    id: int
    slug: Optional[str] = None
    is_published: bool = True
    is_featured: bool = False
    sort_order: int = 0
    views_count: int = 0
    meta_title_uk: Optional[str] = None
    meta_title_en: Optional[str] = None
    meta_description_uk: Optional[str] = None
    meta_description_en: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Схема для списку дизайнів з категорією
class DesignWithCategory(Design):
    category_rel: Optional[DesignCategory] = None


# ============ СХЕМИ ПАКЕТІВ ============

class PackageBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price_uk: str = Field(min_length=1, max_length=255)
    price_en: str = Field(min_length=1, max_length=255)
    duration_uk: str = Field(min_length=1, max_length=255)
    duration_en: str = Field(min_length=1, max_length=255)
    features_uk: List[str] = Field(min_items=1)
    features_en: List[str] = Field(min_items=1)
    advantages_uk: Optional[List[str]] = None
    advantages_en: Optional[List[str]] = None
    process_uk: Optional[List[str]] = None
    process_en: Optional[List[str]] = None
    support_uk: Optional[str] = None
    support_en: Optional[str] = None
    is_popular: bool = False

    @validator('features_uk', 'features_en', 'advantages_uk', 'advantages_en', 'process_uk', 'process_en')
    def validate_lists(cls, v):
        if v is not None:
            return [item.strip() for item in v if item.strip()]
        return v


class PackageCreate(PackageBase):
    sort_order: int = 0
    meta_title_uk: Optional[str] = Field(None, max_length=255)
    meta_title_en: Optional[str] = Field(None, max_length=255)
    meta_description_uk: Optional[str] = Field(None, max_length=320)
    meta_description_en: Optional[str] = Field(None, max_length=320)


class PackageUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    price_uk: Optional[str] = Field(None, min_length=1, max_length=255)
    price_en: Optional[str] = Field(None, min_length=1, max_length=255)
    duration_uk: Optional[str] = Field(None, min_length=1, max_length=255)
    duration_en: Optional[str] = Field(None, min_length=1, max_length=255)
    features_uk: Optional[List[str]] = None
    features_en: Optional[List[str]] = None
    advantages_uk: Optional[List[str]] = None
    advantages_en: Optional[List[str]] = None
    process_uk: Optional[List[str]] = None
    process_en: Optional[List[str]] = None
    support_uk: Optional[str] = None
    support_en: Optional[str] = None
    is_popular: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    meta_title_uk: Optional[str] = Field(None, max_length=255)
    meta_title_en: Optional[str] = Field(None, max_length=255)
    meta_description_uk: Optional[str] = Field(None, max_length=320)
    meta_description_en: Optional[str] = Field(None, max_length=320)


class Package(PackageBase):
    id: int
    slug: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0
    meta_title_uk: Optional[str] = None
    meta_title_en: Optional[str] = None
    meta_description_uk: Optional[str] = None
    meta_description_en: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ НОВЫЕ СХЕМЫ: О НАС И КОМАНДА ============

# Схемы для членов команды
class TeamMemberBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    role_uk: str = Field(..., min_length=2, max_length=255)
    role_en: str = Field(..., min_length=2, max_length=255)
    skills: Optional[str] = None
    avatar: Optional[str] = None
    initials: str = Field(..., min_length=2, max_length=3)

    @validator('initials')
    def validate_initials(cls, v):
        if not v or not v.strip():
            raise ValueError('Initials are required')
        return v.strip().upper()

    @validator('skills')
    def validate_skills(cls, v):
        if v:
            return v.strip()
        return v


class TeamMemberCreate(TeamMemberBase):
    order_index: int = 0
    is_active: bool = True


class TeamMemberUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    role_uk: Optional[str] = Field(None, min_length=2, max_length=255)
    role_en: Optional[str] = Field(None, min_length=2, max_length=255)
    skills: Optional[str] = None
    avatar: Optional[str] = None
    initials: Optional[str] = Field(None, min_length=2, max_length=3)
    order_index: Optional[int] = None
    is_active: Optional[bool] = None

    @validator('initials')
    def validate_initials(cls, v):
        if v:
            return v.strip().upper()
        return v


class TeamMember(TeamMemberBase):
    id: int
    order_index: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Схемы для контента страницы О нас
class AboutContentBase(BaseModel):
    hero_description_uk: Optional[str] = None
    hero_description_en: Optional[str] = None
    mission_uk: Optional[str] = None
    mission_en: Optional[str] = None
    vision_uk: Optional[str] = None
    vision_en: Optional[str] = None
    why_choose_us_uk: Optional[str] = None
    why_choose_us_en: Optional[str] = None
    cta_title_uk: Optional[str] = None
    cta_title_en: Optional[str] = None
    cta_description_uk: Optional[str] = None
    cta_description_en: Optional[str] = None


class AboutContentCreate(AboutContentBase):
    pass


class AboutContentUpdate(AboutContentBase):
    pass


class AboutContent(AboutContentBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Комбинированная схема для страницы "О нас" с командой
class AboutPageResponse(AboutContent):
    team: List[TeamMember] = []

    class Config:
        from_attributes = True


# ============ СХЕМИ ВІДГУКІВ ============

class ReviewBase(BaseModel):
    text_uk: str = Field(min_length=20, max_length=1000)
    text_en: str = Field(min_length=20, max_length=1000)
    rating: int = Field(ge=1, le=5)
    company: Optional[str] = Field(None, max_length=255)


class ReviewCreateAuth(ReviewBase):
    """Создание отзыва авторизованным пользователем"""
    pass


class ReviewCreateAnonymous(ReviewBase):
    """Создание отзыва анонимным пользователем"""
    author_name: str = Field(min_length=2, max_length=255)
    author_email: EmailStr


class ReviewUpdate(BaseModel):
    text_uk: Optional[str] = Field(None, min_length=20, max_length=1000)
    text_en: Optional[str] = Field(None, min_length=20, max_length=1000)
    rating: Optional[int] = Field(None, ge=1, le=5)
    company: Optional[str] = Field(None, max_length=255)
    is_approved: Optional[bool] = None
    is_featured: Optional[bool] = None
    sort_order: Optional[int] = None


class Review(ReviewBase):
    id: int
    user_id: Optional[int] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    is_approved: bool = False
    is_featured: bool = False
    sort_order: int = 0
    approved_at: Optional[datetime] = None
    approved_by_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ FAQ ============

class FAQBase(BaseModel):
    question_uk: str = Field(min_length=10, max_length=500)
    question_en: str = Field(min_length=10, max_length=500)
    answer_uk: str = Field(min_length=20, max_length=2000)
    answer_en: str = Field(min_length=20, max_length=2000)
    sort_order: int = 0


class FAQCreate(FAQBase):
    is_active: bool = True
    slug_uk: Optional[str] = Field(None, max_length=255)
    slug_en: Optional[str] = Field(None, max_length=255)


class FAQUpdate(BaseModel):
    question_uk: Optional[str] = Field(None, min_length=10, max_length=500)
    question_en: Optional[str] = Field(None, min_length=10, max_length=500)
    answer_uk: Optional[str] = Field(None, min_length=20, max_length=2000)
    answer_en: Optional[str] = Field(None, min_length=20, max_length=2000)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    slug_uk: Optional[str] = Field(None, max_length=255)
    slug_en: Optional[str] = Field(None, max_length=255)


class FAQ(FAQBase):
    id: int
    is_active: bool = True
    slug_uk: Optional[str] = None
    slug_en: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ ЗАЯВОК ============

# Валідатор для телефону/Telegram
def validate_phone_or_telegram(v: str) -> str:
    if not v:
        return v

    # Telegram username або посилання
    telegram_patterns = [
        r'^@[a-zA-Z0-9_]{5,}$',  # @username
        r'^https?://(t\.me|telegram\.me)/[a-zA-Z0-9_]{5,}$',  # t.me/username
        r'^[a-zA-Z0-9_]{5,}$'  # username без @
    ]

    # Номер телефону
    phone_pattern = r'^\+?[1-9][0-9]{7,14}$'

    # Видаляємо пробіли та дефіси з номера телефону
    clean_phone = re.sub(r'[\s-]', '', v)

    # Перевіряємо чи це Telegram
    if any(re.match(pattern, v) for pattern in telegram_patterns):
        return v

    # Перевіряємо чи це телефон
    if re.match(phone_pattern, clean_phone):
        return clean_phone

    raise ValueError('Invalid phone number or Telegram username format')


class QuoteApplicationBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    project_type: str = Field(min_length=2, max_length=255)
    budget: Optional[str] = Field(None, max_length=255)
    description: str = Field(min_length=20, max_length=2000)
    package_id: Optional[int] = None

    @validator('phone')
    def validate_phone(cls, v):
        if v:
            return validate_phone_or_telegram(v)
        return v


class QuoteApplicationCreate(QuoteApplicationBase):
    pass


class QuoteApplicationUpdate(BaseModel):
    status: ApplicationStatus
    response_text: Optional[str] = None


class QuoteApplication(QuoteApplicationBase):
    id: int
    user_id: Optional[int] = None
    status: ApplicationStatus = ApplicationStatus.NEW
    response_text: Optional[str] = None
    processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    user: Optional[UserResponse] = None
    package: Optional[Package] = None

    class Config:
        from_attributes = True


class ConsultationApplicationBase(BaseModel):
    first_name: str = Field(min_length=2, max_length=255)
    last_name: str = Field(min_length=2, max_length=255)
    phone: str = Field(min_length=5, max_length=255)
    telegram: str = Field(min_length=5, max_length=255)
    message: Optional[str] = Field(None, max_length=1000)

    @validator('phone', 'telegram')
    def validate_contact_info(cls, v):
        return validate_phone_or_telegram(v)


class ConsultationApplicationCreate(ConsultationApplicationBase):
    pass


class ConsultationApplicationUpdate(BaseModel):
    status: ApplicationStatus
    consultation_scheduled_at: Optional[datetime] = None
    consultation_completed_at: Optional[datetime] = None
    notes: Optional[str] = None


class ConsultationApplication(ConsultationApplicationBase):
    id: int
    user_id: Optional[int] = None
    status: ApplicationStatus = ApplicationStatus.NEW
    consultation_scheduled_at: Optional[datetime] = None
    consultation_completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ КОНТЕНТУ ============

class ContentBase(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    content_uk: Optional[str] = None
    content_en: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)


class ContentCreate(ContentBase):
    is_active: bool = True


class ContentUpdate(BaseModel):
    content_uk: Optional[str] = None
    content_en: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class Content(ContentBase):
    id: int
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ContactInfoBase(BaseModel):
    phone: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    telegram: Optional[str] = Field(None, max_length=255)
    telegram_url: Optional[str] = Field(None, max_length=500)
    address_uk: Optional[str] = Field(None, max_length=500)
    address_en: Optional[str] = Field(None, max_length=500)
    working_hours_uk: Optional[str] = Field(None, max_length=255)
    working_hours_en: Optional[str] = Field(None, max_length=255)


class ContactInfoUpdate(ContactInfoBase):
    pass


class ContactInfo(ContactInfoBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ SEO ============

class SEOSettingsBase(BaseModel):
    page: str = Field(min_length=1, max_length=255, default="home")
    meta_title_uk: Optional[str] = Field(None, max_length=255)
    meta_title_en: Optional[str] = Field(None, max_length=255)
    meta_description_uk: Optional[str] = Field(None, max_length=320)
    meta_description_en: Optional[str] = Field(None, max_length=320)
    meta_keywords_uk: Optional[str] = None
    meta_keywords_en: Optional[str] = None
    og_title_uk: Optional[str] = Field(None, max_length=255)
    og_title_en: Optional[str] = Field(None, max_length=255)
    og_description_uk: Optional[str] = Field(None, max_length=320)
    og_description_en: Optional[str] = Field(None, max_length=320)
    og_image: Optional[str] = Field(None, max_length=500)
    favicon: Optional[str] = Field(None, max_length=500)
    structured_data: Optional[Dict[str, Any]] = None


class SEOSettingsCreate(SEOSettingsBase):
    pass


class SEOSettingsUpdate(BaseModel):
    meta_title_uk: Optional[str] = Field(None, max_length=255)
    meta_title_en: Optional[str] = Field(None, max_length=255)
    meta_description_uk: Optional[str] = Field(None, max_length=320)
    meta_description_en: Optional[str] = Field(None, max_length=320)
    meta_keywords_uk: Optional[str] = None
    meta_keywords_en: Optional[str] = None
    og_title_uk: Optional[str] = Field(None, max_length=255)
    og_title_en: Optional[str] = Field(None, max_length=255)
    og_description_uk: Optional[str] = Field(None, max_length=320)
    og_description_en: Optional[str] = Field(None, max_length=320)
    og_image: Optional[str] = Field(None, max_length=500)
    favicon: Optional[str] = Field(None, max_length=500)
    structured_data: Optional[Dict[str, Any]] = None


class SEOSettings(SEOSettingsBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ ФАЙЛІВ ============

class UploadedFileBase(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    stored_filename: str = Field(min_length=1, max_length=255)
    file_url: str = Field(min_length=1, max_length=500)
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    mime_type: str = Field(min_length=1, max_length=255)
    file_size: int = Field(gt=0)
    category: str = "other"
    alt_text: Optional[str] = Field(None, max_length=255)


class UploadedFileUpdate(BaseModel):
    alt_text: Optional[str] = Field(None, max_length=255)
    is_used: Optional[bool] = None


class UploadedFile(UploadedFileBase):
    id: int
    file_path: str
    file_extension: str
    folder: Optional[str] = None
    hash: Optional[str] = None
    is_used: bool = False
    uploaded_by_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============ СХЕМИ ПОЛІТИК ============

class PolicyBase(BaseModel):
    type: str = Field(min_length=1, max_length=50)
    title_uk: Optional[str] = Field(None, max_length=255)
    title_en: Optional[str] = Field(None, max_length=255)
    content_uk: Optional[str] = None
    content_en: Optional[str] = None
    version: str = "1.0"


class PolicyCreate(PolicyBase):
    is_active: bool = True


class PolicyUpdate(BaseModel):
    title_uk: Optional[str] = Field(None, max_length=255)
    title_en: Optional[str] = Field(None, max_length=255)
    content_uk: Optional[str] = None
    content_en: Optional[str] = None
    is_active: Optional[bool] = None
    version: Optional[str] = None


class Policy(PolicyBase):
    id: int
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ НАЛАШТУВАНЬ ============

class SettingsCategory(str, Enum):
    GENERAL = "general"
    SEO = "seo"
    BRANDING = "branding"
    SMTP = "smtp"
    ANALYTICS = "analytics"
    FEATURES = "features"


class SiteSettingsBase(BaseModel):
    category: SettingsCategory
    key: str = Field(min_length=1, max_length=255)
    value: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)
    is_public: bool = False


class SiteSettingsCreate(SiteSettingsBase):
    pass


class SiteSettingsUpdate(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)
    is_public: Optional[bool] = None


class SiteSettings(SiteSettingsBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ СХЕМИ ВІДПОВІДЕЙ ============

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24 години в секундах
    user: UserResponse


class Message(BaseModel):
    message: str
    details: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int = 1
    size: int = 20
    pages: int

    @validator('pages', always=True)
    def calculate_pages(cls, v, values):
        total = values.get('total', 0)
        size = values.get('size', 20)
        return (total + size - 1) // size if total > 0 else 0


# ============ СХЕМИ СТАТИСТИКИ ============

class DashboardStats(BaseModel):
    total_applications: int
    new_applications: int
    total_reviews: int
    total_designs: int
    approved_reviews: int
    pending_reviews: int
    total_files: int
    total_file_size: int
    recent_activity: Optional[List[Dict[str, Any]]] = None


class MonthlyStats(BaseModel):
    month: str
    year: int
    visits: int
    page_views: int
    quote_applications: int
    consultation_applications: int


class AnalyticsData(BaseModel):
    period: str
    total_visits: int
    unique_visitors: int
    conversion_rate: float
    popular_pages: List[Dict[str, Union[str, int]]]
    monthly_stats: List[MonthlyStats]


# ============ СХЕМИ EMAIL ============

class EmailTemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    subject_uk: str = Field(min_length=1, max_length=255)
    subject_en: str = Field(min_length=1, max_length=255)
    content_uk: str = Field(min_length=10)
    content_en: str = Field(min_length=10)
    variables: Optional[List[str]] = None
    is_active: bool = True


class EmailTemplateCreate(EmailTemplateBase):
    pass


class EmailTemplateUpdate(BaseModel):
    subject_uk: Optional[str] = Field(None, min_length=1, max_length=255)
    subject_en: Optional[str] = Field(None, min_length=1, max_length=255)
    content_uk: Optional[str] = Field(None, min_length=10)
    content_en: Optional[str] = Field(None, min_length=10)
    variables: Optional[List[str]] = None
    is_active: Optional[bool] = None


class EmailTemplate(EmailTemplateBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EmailSendRequest(BaseModel):
    template_name: str
    recipient_email: EmailStr
    variables: Optional[Dict[str, str]] = None
    language: str = Field(default="uk", pattern=r'^(uk|en)$')


# ============ СХЕМИ ПОШУКУ ============

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    category: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    type: str  # design, package, content
    id: Union[int, str]
    title: str
    description: Optional[str] = None
    url: str
    image: Optional[str] = None
    relevance: float = 0.0


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    query: str
    took: float  # Час виконання запиту в мілісекундах


# ============ ДОДАТКОВІ СХЕМИ ============

class BulkOperationRequest(BaseModel):
    ids: List[int] = Field(min_items=1)
    action: str = Field(min_length=1)
    data: Optional[Dict[str, Any]] = None


class BulkOperationResponse(BaseModel):
    success_count: int
    failed_count: int
    total_count: int
    errors: List[Dict[str, Any]] = []


class FileUploadResponse(BaseModel):
    id: int
    filename: str
    url: str
    thumbnail_url: Optional[str] = None
    size: int
    mime_type: str
    category: str


class PublicConfig(BaseModel):
    app_name: str
    version: str
    max_file_size: int
    allowed_extensions: List[str]
    features: Dict[str, bool]
    contact_info: Optional[ContactInfo] = None
    seo_settings: Optional[Dict[str, SEOSettings]] = None