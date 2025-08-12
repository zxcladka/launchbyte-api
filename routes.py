from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request, Response, \
    BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc, func, or_, and_, text
from typing import List, Optional, Dict, Any, Union
from datetime import timedelta, datetime
import os
import uuid
from pathlib import Path
import logging
import json

from database import get_db
import models
import schemas
from auth import *
from config import settings
from utils import (
    save_uploaded_file, delete_file,
    slugify, split_features_string, join_features_list,
    get_upload_stats
)

# Налаштування логування
logger = logging.getLogger(__name__)

router = APIRouter()


# ============ HELPER FUNCTIONS ============

def generate_slug(title: str, model_class, db: Session, id_to_exclude: Optional[int] = None) -> str:
    """Генерує унікальний slug для моделі."""
    base_slug = slugify(title)
    slug = base_slug
    counter = 1

    while True:
        query = db.query(model_class).filter(model_class.slug == slug)
        if id_to_exclude:
            query = query.filter(model_class.id != id_to_exclude)

        if not query.first():
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1


def update_design_category_counts(db: Session):
    """Оновлює лічильники дизайнів в категоріях."""
    try:
        categories = db.query(models.DesignCategory).all()
        for category in categories:
            count = db.query(models.Design).filter(
                models.Design.category_id == category.id,
                models.Design.is_published == True
            ).count()
            # У моделі немає поля count, тому просто пропускаємо це
        db.commit()
    except Exception as e:
        logger.error(f"Error updating category counts: {e}")


# ============ ERROR HANDLERS (для використання на рівні app) ============

async def value_error_handler(request: Request, exc: ValueError):
    """Обробник помилок валідації."""
    logger.warning(f"ValueError: {exc}")
    return JSONResponse(
        status_code=400,
        content={"error": "Validation Error", "message": str(exc)}
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """Обробник HTTP помилок."""
    logger.warning(f"HTTPException: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTP Error", "message": exc.detail}
    )


# ============ АВТОРИЗАЦІЯ (КРИТИЧНО ИСПРАВЛЕНО) ============

@router.post("/auth/register", response_model=schemas.Token)
async def register(user_data: schemas.UserCreate, response: Response, db: Session = Depends(get_db)):
    """Реєстрація нового користувача."""
    try:
        # Перевіряємо чи користувач вже існує
        existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="User with this email already exists"
            )

        user = create_user(db, user_data.email, user_data.name, user_data.password)

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )

        # ИСПРАВЛЕНО: правильно устанавливаем cookie
        set_auth_cookie(response, access_token)

        logger.info(f"New user registered: {user.email}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": user
        }
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/auth/login", response_model=schemas.Token)
async def login(user_data: schemas.UserLogin, response: Response, db: Session = Depends(get_db)):
    """Вхід користувача (КРИТИЧНО ИСПРАВЛЕНО)."""
    user = authenticate_user(db, user_data.email, user_data.password)
    if not user:
        logger.warning(f"Failed login attempt: {user_data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )

    # Обновляем время последнего входа
    user.last_login = datetime.utcnow()
    user.updated_at = datetime.utcnow()
    db.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    # КРИТИЧНО ИСПРАВЛЕНО: правильно устанавливаем cookie с корректными настройками
    set_auth_cookie(response, access_token)

    logger.info(f"User logged in: {user.email}")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": user
    }


@router.post("/auth/logout", response_model=schemas.Message)
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Вихід користувача (КРИТИЧНО ИСПРАВЛЕНО)."""
    try:
        # Пытаемся получить токен для blacklist
        token = get_token_from_cookie_or_header(request, None)
        if token:
            blacklist_token(token, "logout")

        # КРИТИЧНО ИСПРАВЛЕНО: правильно очищаем все cookie
        clear_auth_cookie(response)

        logger.info("User logged out successfully")
        return {"message": "Successfully logged out"}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        # Все равно очищаем cookies даже при ошибке
        clear_auth_cookie(response)
        return {"message": "Successfully logged out"}


@router.get("/auth/me", response_model=schemas.UserResponse)
async def get_current_user_profile(
        current_user: models.User = Depends(get_current_active_user)
):
    """Отримати профіль поточного користувача."""
    return current_user


@router.put("/auth/me", response_model=schemas.UserResponse)
async def update_current_user_profile(
        user_data: schemas.UserUpdate,
        current_user: models.User = Depends(get_current_active_user),
        db: Session = Depends(get_db)
):
    """Оновити профіль поточного користувача."""
    if user_data.name is not None:
        current_user.name = user_data.name
    if user_data.avatar_url is not None:
        current_user.avatar_url = user_data.avatar_url

    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)

    logger.info(f"User profile updated: {current_user.email}")
    return current_user


@router.post("/auth/change-password", response_model=schemas.PasswordChangeResponse)
async def change_password(
        password_data: schemas.PasswordChangeRequest,
        current_user: models.User = Depends(get_current_active_user),
        db: Session = Depends(get_db)
):
    """Сменить пароль текущего пользователя."""
    try:
        # Проверяем текущий пароль
        if not verify_password(password_data.current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )

        # Проверяем что новый пароль отличается от текущего
        if verify_password(password_data.new_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password"
            )

        # Обновляем пароль
        current_user.hashed_password = get_password_hash(password_data.new_password)
        current_user.password_changed_at = datetime.utcnow()
        current_user.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(current_user)

        logger.info(f"Password changed for user: {current_user.email}")

        return schemas.PasswordChangeResponse(
            message="Password changed successfully",
            changed_at=current_user.password_changed_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password for {current_user.email}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )


# ============ ДИЗАЙНЫ ============

@router.get("/designs", response_model=List[schemas.DesignWithCategory])
async def get_designs(
        category: Optional[str] = None,
        search: Optional[str] = None,
        featured: Optional[bool] = None,
        published: Optional[bool] = True,
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        db: Session = Depends(get_db)
):
    """Отримати список дизайнів."""
    try:
        query = db.query(models.Design).options(joinedload(models.Design.category_rel))

        # Фільтри
        if published is not None:
            query = query.filter(models.Design.is_published == published)

        if category and category != "all":
            query = query.filter(models.Design.category_id == category)

        if featured is not None:
            query = query.filter(models.Design.is_featured == featured)

        if search:
            search_filter = or_(
                models.Design.title.ilike(f"%{search}%"),
                models.Design.description_uk.ilike(f"%{search}%"),
                models.Design.description_en.ilike(f"%{search}%"),
                models.Design.technology.ilike(f"%{search}%")
            )
            query = query.filter(search_filter)

        # Сортування
        query = query.order_by(
            desc(models.Design.is_featured),
            models.Design.sort_order,
            desc(models.Design.created_at)
        )

        designs = query.offset(skip).limit(limit).all()

        # Оновлюємо лічільник переглядів для кожного дизайну
        for design in designs:
            design.views_count += 1
        db.commit()

        return designs
    except Exception as e:
        logger.error(f"Error fetching designs: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch designs")


@router.get("/designs/{design_id}", response_model=schemas.DesignWithCategory)
async def get_design(design_id: int, db: Session = Depends(get_db)):
    """Отримати дизайн за ID."""
    design = db.query(models.Design).options(joinedload(models.Design.category_rel)).filter(
        models.Design.id == design_id
    ).first()

    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    # Оновлюємо лічільник переглядів
    design.views_count += 1
    db.commit()

    return design


@router.get("/designs/slug/{slug}", response_model=schemas.DesignWithCategory)
async def get_design_by_slug(slug: str, db: Session = Depends(get_db)):
    """Отримати дизайн за slug."""
    design = db.query(models.Design).options(joinedload(models.Design.category_rel)).filter(
        models.Design.slug == slug,
        models.Design.is_published == True
    ).first()

    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    # Оновлюємо лічільник переглядів
    design.views_count += 1
    db.commit()

    return design


@router.post("/designs", response_model=schemas.Design)
async def create_design(
        design_data: schemas.DesignCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити новий дизайн (тільки адмін)."""
    # Перевіряємо чи існує категорія
    category = db.query(models.DesignCategory).filter(
        models.DesignCategory.id == design_data.category_id
    ).first()
    if not category:
        raise HTTPException(status_code=400, detail="Category not found")

    # Генеруємо slug
    slug = generate_slug(design_data.title, models.Design, db)

    design_dict = design_data.dict()
    design_dict['slug'] = slug

    design = models.Design(**design_dict)
    db.add(design)
    db.commit()
    db.refresh(design)

    # Оновлюємо лічільник категорії
    update_design_category_counts(db)

    logger.info(f"Design created: {design.title} by {current_user.email}")
    return design


@router.put("/designs/{design_id}", response_model=schemas.Design)
async def update_design(
        design_id: int,
        design_data: schemas.DesignUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити дизайн (тільки адмін)."""
    design = db.query(models.Design).filter(models.Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    old_category = design.category_id
    update_data = design_data.dict(exclude_unset=True)

    # Якщо змінюється заголовок, оновлюємо slug
    if 'title' in update_data:
        update_data['slug'] = generate_slug(update_data['title'], models.Design, db, design_id)

    # Перевіряємо нову категорію
    if 'category_id' in update_data:
        category = db.query(models.DesignCategory).filter(
            models.DesignCategory.id == update_data['category_id']
        ).first()
        if not category:
            raise HTTPException(status_code=400, detail="Category not found")

    for field, value in update_data.items():
        setattr(design, field, value)

    design.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(design)

    # Оновлюємо лічільники категорій
    if old_category != design.category_id:
        update_design_category_counts(db)

    logger.info(f"Design updated: {design.title} by {current_user.email}")
    return design


@router.delete("/designs/{design_id}", response_model=schemas.Message)
async def delete_design(
        design_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити дизайн (тільки адмін)."""
    design = db.query(models.Design).filter(models.Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    design_title = design.title
    db.delete(design)
    db.commit()

    # Оновлюємо лічільники категорій
    update_design_category_counts(db)

    logger.info(f"Design deleted: {design_title} by {current_user.email}")
    return {"message": "Design deleted successfully"}


# ============ КАТЕГОРІЇ ДИЗАЙНІВ (КРИТИЧНО ИСПРАВЛЕНО) ============

@router.get("/design-categories", response_model=List[schemas.DesignCategory])
async def get_design_categories(
        include_inactive: bool = False,
        db: Session = Depends(get_db)
):
    """Отримати список категорій дизайнів."""
    try:
        query = db.query(models.DesignCategory)

        if not include_inactive:
            query = query.filter(models.DesignCategory.is_active == True)

        categories = query.order_by(models.DesignCategory.sort_order, models.DesignCategory.id).all()
        logger.info(f"Fetched {len(categories)} design categories")
        return categories
    except Exception as e:
        logger.error(f"Error fetching design categories: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch design categories")


@router.post("/design-categories", response_model=schemas.DesignCategory)
async def create_design_category(
        category_data: schemas.DesignCategoryCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити нову категорію дизайнів (тільки адмін) - КРИТИЧНО ИСПРАВЛЕНО."""
    try:
        # ИСПРАВЛЕНИЕ: Проверяем каждое поле отдельно
        existing_id = db.query(models.DesignCategory).filter(
            models.DesignCategory.id == category_data.id
        ).first()
        if existing_id:
            raise HTTPException(status_code=400, detail=f"Category with ID '{category_data.id}' already exists")

        existing_slug = db.query(models.DesignCategory).filter(
            models.DesignCategory.slug == category_data.slug
        ).first()
        if existing_slug:
            raise HTTPException(status_code=400, detail=f"Category with slug '{category_data.slug}' already exists")

        # ИСПРАВЛЕНИЕ: Проверяем название на уникальность
        if hasattr(category_data, 'title_uk') and category_data.title_uk:
            existing_title_uk = db.query(models.DesignCategory).filter(
                models.DesignCategory.title_uk == category_data.title_uk
            ).first()
            if existing_title_uk:
                raise HTTPException(status_code=400,
                                    detail=f"Category with Ukrainian title '{category_data.title_uk}' already exists")

        # Создаем категорию
        category_dict = category_data.dict()
        category = models.DesignCategory(**category_dict)

        db.add(category)
        db.flush()  # КРИТИЧНО: применяем перед commit
        db.commit()
        db.refresh(category)

        logger.info(
            f"✅ Design category created: {category.id} ({getattr(category, 'title_uk', category.id)}) by {current_user.email}")
        return category

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"❌ Error creating design category: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create design category: {str(e)}")


@router.put("/design-categories/{category_id}", response_model=schemas.DesignCategory)
async def update_design_category(
        category_id: str,
        category_data: schemas.DesignCategoryUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити категорію дизайнів (тільки адмін) - КРИТИЧНО ИСПРАВЛЕНО."""
    try:
        category = db.query(models.DesignCategory).filter(
            models.DesignCategory.id == category_id
        ).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        # ИСПРАВЛЕНИЕ: Обновляем только непустые поля
        update_data = category_data.dict(exclude_unset=True, exclude_none=True)

        # Проверяем уникальность slug при изменении
        if 'slug' in update_data and update_data['slug'] != category.slug:
            existing_slug = db.query(models.DesignCategory).filter(
                models.DesignCategory.slug == update_data['slug'],
                models.DesignCategory.id != category_id
            ).first()
            if existing_slug:
                raise HTTPException(status_code=400, detail="Category with this slug already exists")

        # Применяем изменения
        for field, value in update_data.items():
            if hasattr(category, field) and value is not None:
                setattr(category, field, value)
                logger.debug(f"Updated category field {field} = {value}")

        category.updated_at = datetime.utcnow()

        db.flush()  # КРИТИЧНО: Применяем изменения к объекту
        db.commit()  # Сохраняем в БД
        db.refresh(category)  # Обновляем объект из БД

        logger.info(f"✅ Design category updated: {category.id} by {current_user.email}")
        return category

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating design category {category_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update design category: {str(e)}")


@router.delete("/design-categories/{category_id}", response_model=schemas.Message)
async def delete_design_category(
        category_id: str,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити категорію дизайнів (тільки адмін) - КРИТИЧНО ИСПРАВЛЕНО."""
    try:
        # Перевіряємо чи є дизайни в цій категорії
        designs_count = db.query(models.Design).filter(models.Design.category_id == category_id).count()
        if designs_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete category that contains {designs_count} designs"
            )

        category = db.query(models.DesignCategory).filter(
            models.DesignCategory.id == category_id
        ).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        category_name = category.name_uk or category.id
        db.delete(category)
        db.commit()

        logger.info(f"✅ Design category deleted: {category_id} ({category_name}) by {current_user.email}")
        return {"message": "Category deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting design category {category_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete design category: {str(e)}")


# ============ УПРАВЛЕНИЕ СТРАНИЦЕЙ "О НАС" ============

@router.get("/content/about", response_model=schemas.AboutPageResponse)
async def get_about_content(db: Session = Depends(get_db)):
    """Получить контент страницы 'О нас' с командой."""
    try:
        # Получаем контент страницы
        about_content = db.query(models.AboutContent).first()

        # Если нет контента, создаем пустую запись
        if not about_content:
            about_content = models.AboutContent()
            db.add(about_content)
            db.commit()
            db.refresh(about_content)

        # Получаем активных членов команды
        team_members = db.query(models.TeamMember).filter(
            models.TeamMember.is_active == True
        ).order_by(
            models.TeamMember.order_index,
            models.TeamMember.id
        ).all()

        # Формируем ответ
        response_data = about_content.__dict__.copy()
        response_data['team'] = team_members

        return schemas.AboutPageResponse(**response_data)

    except Exception as e:
        logger.error(f"Error fetching about content: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch about content")


@router.put("/content/about", response_model=schemas.AboutContent)
async def update_about_content(
        content_data: schemas.AboutContentUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Обновить контент страницы 'О нас' (только админ)."""
    try:
        # Получаем существующий контент или создаем новый
        about_content = db.query(models.AboutContent).first()

        if not about_content:
            # Создаем новый контент
            about_content = models.AboutContent(**content_data.dict(exclude_unset=True))
            db.add(about_content)
            logger.info(f"About content created by {current_user.email}")
        else:
            # Обновляем существующий
            update_data = content_data.dict(exclude_unset=True)
            for field, value in update_data.items():
                setattr(about_content, field, value)
            about_content.updated_at = datetime.utcnow()
            logger.info(f"About content updated by {current_user.email}")

        db.commit()
        db.refresh(about_content)

        return about_content

    except Exception as e:
        logger.error(f"Error updating about content: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update about content")


# ============ УПРАВЛЕНИЕ КОМАНДОЙ ============

@router.get("/team", response_model=List[schemas.TeamMember])
async def get_team_members(
        include_inactive: bool = False,
        db: Session = Depends(get_db)
):
    """Получить список членов команды."""
    try:
        query = db.query(models.TeamMember)

        if not include_inactive:
            query = query.filter(models.TeamMember.is_active == True)

        team_members = query.order_by(
            models.TeamMember.order_index,
            models.TeamMember.id
        ).all()

        return team_members

    except Exception as e:
        logger.error(f"Error fetching team members: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch team members")


@router.post("/team", response_model=schemas.TeamMember)
async def create_team_member(
        member_data: schemas.TeamMemberCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Добавить нового члена команды (только админ)."""
    try:
        # Проверяем уникальность имени
        existing_member = db.query(models.TeamMember).filter(
            models.TeamMember.name == member_data.name,
            models.TeamMember.is_active == True
        ).first()

        if existing_member:
            raise HTTPException(
                status_code=400,
                detail="Team member with this name already exists"
            )

        # Если order_index не указан, ставим в конец
        if member_data.order_index == 0:
            max_order = db.query(func.max(models.TeamMember.order_index)).scalar() or 0
            member_data.order_index = max_order + 1

        team_member = models.TeamMember(**member_data.dict())
        db.add(team_member)
        db.commit()
        db.refresh(team_member)

        logger.info(f"Team member created: {team_member.name} by {current_user.email}")
        return team_member

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating team member: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create team member")


@router.put("/team/{member_id}", response_model=schemas.TeamMember)
async def update_team_member(
        member_id: int,
        member_data: schemas.TeamMemberUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Обновить члена команды (только админ)."""
    try:
        team_member = db.query(models.TeamMember).filter(
            models.TeamMember.id == member_id
        ).first()

        if not team_member:
            raise HTTPException(status_code=404, detail="Team member not found")

        # Проверяем уникальность имени (если меняется)
        if member_data.name and member_data.name != team_member.name:
            existing_member = db.query(models.TeamMember).filter(
                models.TeamMember.name == member_data.name,
                models.TeamMember.is_active == True,
                models.TeamMember.id != member_id
            ).first()

            if existing_member:
                raise HTTPException(
                    status_code=400,
                    detail="Team member with this name already exists"
                )

        # Обновляем поля
        update_data = member_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(team_member, field, value)

        team_member.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(team_member)

        logger.info(f"Team member updated: {team_member.name} by {current_user.email}")
        return team_member

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating team member: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update team member")


@router.delete("/team/{member_id}", response_model=schemas.Message)
async def delete_team_member(
        member_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Удалить члена команды (только админ)."""
    try:
        team_member = db.query(models.TeamMember).filter(
            models.TeamMember.id == member_id
        ).first()

        if not team_member:
            raise HTTPException(status_code=404, detail="Team member not found")

        member_name = team_member.name
        db.delete(team_member)
        db.commit()

        logger.info(f"Team member deleted: {member_name} by {current_user.email}")
        return {"message": "Team member deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting team member: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete team member")


@router.patch("/team/{member_id}/toggle-active", response_model=schemas.TeamMember)
async def toggle_team_member_active(
        member_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Переключить активность члена команды (только админ)."""
    try:
        team_member = db.query(models.TeamMember).filter(
            models.TeamMember.id == member_id
        ).first()

        if not team_member:
            raise HTTPException(status_code=404, detail="Team member not found")

        team_member.is_active = not team_member.is_active
        team_member.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(team_member)

        status = "activated" if team_member.is_active else "deactivated"
        logger.info(f"Team member {status}: {team_member.name} by {current_user.email}")

        return team_member

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling team member status: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update team member status")


@router.patch("/team/reorder", response_model=schemas.Message)
async def reorder_team_members(
        member_ids: List[int],
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Изменить порядок членов команды (только админ)."""
    try:
        # Обновляем order_index для каждого члена команды
        for index, member_id in enumerate(member_ids):
            team_member = db.query(models.TeamMember).filter(
                models.TeamMember.id == member_id
            ).first()

            if team_member:
                team_member.order_index = index
                team_member.updated_at = datetime.utcnow()

        db.commit()

        logger.info(f"Team members reordered by {current_user.email}")
        return {"message": "Team members reordered successfully"}

    except Exception as e:
        logger.error(f"Error reordering team members: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to reorder team members")


# ============ ПАКЕТИ (ИСПРАВЛЕНО ДЛЯ ГЛАВНОЙ СТРАНИЦЫ) ============

@router.get("/packages", response_model=List[schemas.Package])
async def get_packages(
        active_only: bool = True,
        db: Session = Depends(get_db)
):
    """Отримати список пакетів."""
    query = db.query(models.Package)

    if active_only:
        query = query.filter(models.Package.is_active == True)

    packages = query.order_by(
        desc(models.Package.is_popular),
        models.Package.sort_order,
        models.Package.id
    ).all()
    return packages


# КРИТИЧНО ИСПРАВЛЕНО: Получить ограниченное количество пакетов для главной страницы
@router.get("/packages/homepage", response_model=List[schemas.Package])
async def get_homepage_packages(
        limit: int = Query(2, ge=1, le=10, description="Максимальна кількість пакетів для головної сторінки"),
        db: Session = Depends(get_db)
):
    """Отримати пакети для головної сторінки (максимум 2) - КРИТИЧНО ИСПРАВЛЕНО."""
    try:
        packages = db.query(models.Package).filter(
            models.Package.is_active == True
        ).order_by(
            desc(models.Package.is_popular),  # Сначала популярные
            models.Package.sort_order,  # Потом по порядку сортировки
            models.Package.id  # И наконец по ID
        ).limit(limit).all()

        logger.info(f"✅ Fetched {len(packages)} packages for homepage (limit: {limit})")
        return packages

    except Exception as e:
        logger.error(f"❌ Error fetching homepage packages: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch packages for homepage")


@router.get("/packages/{package_id}", response_model=schemas.Package)
async def get_package(package_id: int, db: Session = Depends(get_db)):
    """Отримати пакет за ID."""
    package = db.query(models.Package).filter(models.Package.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


@router.get("/packages/slug/{slug}", response_model=schemas.Package)
async def get_package_by_slug(slug: str, db: Session = Depends(get_db)):
    """Отримати пакет за slug."""
    package = db.query(models.Package).filter(
        models.Package.slug == slug,
        models.Package.is_active == True
    ).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


@router.post("/packages", response_model=schemas.Package)
async def create_package(
        package_data: schemas.PackageCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити новий пакет (тільки адмін)."""
    # Генеруємо slug
    slug = generate_slug(package_data.name, models.Package, db)

    package_dict = package_data.dict()
    package_dict['slug'] = slug

    package = models.Package(**package_dict)
    db.add(package)
    db.commit()
    db.refresh(package)

    logger.info(f"Package created: {package.name} by {current_user.email}")
    return package


@router.put("/packages/{package_id}", response_model=schemas.Package)
async def update_package(
        package_id: int,
        package_data: schemas.PackageUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити пакет (тільки адмін)."""
    package = db.query(models.Package).filter(models.Package.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    update_data = package_data.dict(exclude_unset=True)

    # Якщо змінюється назва, оновлюємо slug
    if 'name' in update_data:
        update_data['slug'] = generate_slug(update_data['name'], models.Package, db, package_id)

    for field, value in update_data.items():
        setattr(package, field, value)

    package.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(package)

    logger.info(f"Package updated: {package.name} by {current_user.email}")
    return package


@router.delete("/packages/{package_id}", response_model=schemas.Message)
async def delete_package(
        package_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити пакет (тільки адмін)."""
    package = db.query(models.Package).filter(models.Package.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    # Перевіряємо чи є заявки з цим пакетом
    applications_count = db.query(models.QuoteApplication).filter(
        models.QuoteApplication.package_id == package_id
    ).count()

    if applications_count > 0:
        # Не видаляємо, а деактивуємо
        package.is_active = False
        db.commit()
        logger.info(f"Package deactivated (has {applications_count} applications): {package.name}")
        return {"message": f"Package deactivated due to {applications_count} existing applications"}

    package_name = package.name
    db.delete(package)
    db.commit()

    logger.info(f"Package deleted: {package_name} by {current_user.email}")
    return {"message": "Package deleted successfully"}


# ============ ВІДГУКИ ============

@router.get("/reviews", response_model=List[schemas.Review])
async def get_reviews(
        approved_only: bool = False,
        featured_only: bool = False,
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        db: Session = Depends(get_db)
):
    """Отримати список відгуків."""
    query = db.query(models.Review).options(joinedload(models.Review.user))

    if approved_only:
        query = query.filter(models.Review.is_approved == True)

    if featured_only:
        query = query.filter(models.Review.is_featured == True)

    reviews = query.order_by(
        desc(models.Review.is_featured),
        models.Review.sort_order,
        desc(models.Review.created_at)
    ).offset(skip).limit(limit).all()

    return reviews


@router.get("/reviews/public", response_model=List[schemas.Review])
async def get_public_reviews(
        featured_only: bool = False,
        skip: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
        db: Session = Depends(get_db)
):
    """Отримати публічні відгуки (тільки схвалені) для головної сторінки."""
    query = db.query(models.Review).options(joinedload(models.Review.user)).filter(
        models.Review.is_approved == True  # Только одобренные отзывы
    )

    if featured_only:
        query = query.filter(models.Review.is_featured == True)

    reviews = query.order_by(
        desc(models.Review.is_featured),
        models.Review.sort_order,
        desc(models.Review.created_at)
    ).offset(skip).limit(limit).all()

    return reviews


@router.get("/reviews/pending", response_model=List[schemas.Review])
async def get_pending_reviews(
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Отримати відгуки на модерації (тільки адмін)."""
    reviews = db.query(models.Review).options(joinedload(models.Review.user)).filter(
        models.Review.is_approved == False
    ).order_by(desc(models.Review.created_at)).offset(skip).limit(limit).all()

    return reviews


@router.post("/reviews", response_model=schemas.Review)
async def create_review(
        review_data: schemas.ReviewCreateAuth,
        current_user: models.User = Depends(get_current_active_user),
        db: Session = Depends(get_db)
):
    """Створити новий відгук."""
    # Перевіряємо чи користувач вже залишав відгук
    existing_review = db.query(models.Review).filter(
        models.Review.user_id == current_user.id
    ).first()
    if existing_review:
        raise HTTPException(
            status_code=400,
            detail="You have already submitted a review"
        )

    # Автоматически одобряем отзывы от зарегистрированных пользователей
    review = models.Review(
        **review_data.dict(),
        user_id=current_user.id,
        is_approved=True,  # Автоматически одобряем
        approved_at=datetime.utcnow(),  # Устанавливаем время одобрения
        approved_by_id=current_user.id  # Одобрено самим пользователем
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    # Завантажуємо користувача для відповіді
    review = db.query(models.Review).options(joinedload(models.Review.user)).filter(
        models.Review.id == review.id
    ).first()

    logger.info(f"Review created and auto-approved by {current_user.email}")
    return review


@router.post("/reviews/anonymous", response_model=schemas.Review)
async def create_anonymous_review(
        review_data: schemas.ReviewCreateAnonymous,
        db: Session = Depends(get_db)
):
    """Створити анонімний відгук."""
    try:
        # Перевіряємо чи не було вже відгуку з такого email
        existing_review = db.query(models.Review).filter(
            models.Review.author_email == review_data.author_email
        ).first()
        if existing_review:
            raise HTTPException(
                status_code=400,
                detail="Review from this email already exists"
            )

        review_dict = review_data.dict()
        # Анонимные отзывы требуют модерации
        review_dict['is_approved'] = False  # Анонимные отзывы требуют одобрения

        review = models.Review(**review_dict)
        db.add(review)
        db.commit()
        db.refresh(review)

        logger.info(f"Anonymous review created from {review_data.author_email} (requires moderation)")
        return review
    except Exception as e:
        logger.error(f"Error creating anonymous review: {e}")
        raise HTTPException(status_code=500, detail="Failed to create review")


@router.patch("/reviews/{review_id}/approve", response_model=schemas.Review)
async def approve_review(
        review_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Схвалити відгук (тільки адмін)."""
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_approved = True
    review.approved_at = datetime.utcnow()
    review.approved_by_id = current_user.id
    review.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(review)

    # Завантажуємо користувача
    review = db.query(models.Review).options(joinedload(models.Review.user)).filter(
        models.Review.id == review.id
    ).first()

    logger.info(f"Review approved: {review_id} by {current_user.email}")
    return review


@router.patch("/reviews/{review_id}/reject", response_model=schemas.Message)
async def reject_review(
        review_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Відхилити відгук (тільки адмін)."""
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    db.delete(review)
    db.commit()

    logger.info(f"Review rejected and deleted: {review_id} by {current_user.email}")
    return {"message": "Review rejected and deleted"}


@router.put("/reviews/{review_id}", response_model=schemas.Review)
async def update_review(
        review_id: int,
        review_data: schemas.ReviewUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити відгук (тільки адмін)."""
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    update_data = review_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(review, field, value)

    review.updated_at = datetime.utcnow()
    db.commit()

    # Завантажуємо з користувачем
    review = db.query(models.Review).options(joinedload(models.Review.user)).filter(
        models.Review.id == review.id
    ).first()

    logger.info(f"Review updated: {review_id} by {current_user.email}")
    return review


@router.delete("/reviews/{review_id}", response_model=schemas.Message)
async def delete_review(
        review_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити відгук (тільки адмін)."""
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    db.delete(review)
    db.commit()

    logger.info(f"Review deleted: {review_id} by {current_user.email}")
    return {"message": "Review deleted successfully"}


# ============ FAQ ============

@router.get("/faq", response_model=List[schemas.FAQ])
async def get_faq(
        active_only: bool = True,
        db: Session = Depends(get_db)
):
    """Отримати список FAQ."""
    query = db.query(models.FAQ)

    if active_only:
        query = query.filter(models.FAQ.is_active == True)

    faqs = query.order_by(models.FAQ.sort_order, models.FAQ.id).all()
    return faqs


@router.post("/faq", response_model=schemas.FAQ)
async def create_faq(
        faq_data: schemas.FAQCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити нове FAQ (тільки адмін)."""
    faq = models.FAQ(**faq_data.dict())
    db.add(faq)
    db.commit()
    db.refresh(faq)

    logger.info(f"FAQ created by {current_user.email}")
    return faq


@router.put("/faq/{faq_id}", response_model=schemas.FAQ)
async def update_faq(
        faq_id: int,
        faq_data: schemas.FAQUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити FAQ (тільки адмін)."""
    faq = db.query(models.FAQ).filter(models.FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    update_data = faq_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(faq, field, value)

    faq.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(faq)

    logger.info(f"FAQ updated: {faq_id} by {current_user.email}")
    return faq


@router.delete("/faq/{faq_id}", response_model=schemas.Message)
async def delete_faq(
        faq_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити FAQ (тільки адмін)."""
    faq = db.query(models.FAQ).filter(models.FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    db.delete(faq)
    db.commit()

    logger.info(f"FAQ deleted: {faq_id} by {current_user.email}")
    return {"message": "FAQ deleted successfully"}


# ============ ЗАЯВКИ ============

@router.post("/applications/quote", response_model=schemas.QuoteApplication)
async def create_quote_application(
        application_data: schemas.QuoteApplicationCreate,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    """Створити заявку на прорахунок."""
    try:
        package = None

        # Улучшена проверка пакета
        if application_data.package_id:
            package = db.query(models.Package).filter(
                models.Package.id == application_data.package_id
            ).first()

            if not package:
                logger.warning(f"Package not found: {application_data.package_id}")
                # Более мягкая обработка ошибки - создаем заявку без пакета
                application_data.package_id = None
                logger.info(f"Creating quote application without package for {application_data.email}")
            elif not package.is_active:
                logger.warning(f"Package is inactive: {application_data.package_id}")
                # Если пакет неактивен, создаем заявку без пакета
                application_data.package_id = None
                logger.info(f"Creating quote application without inactive package for {application_data.email}")

        application = models.QuoteApplication(**application_data.dict())
        db.add(application)
        db.commit()
        db.refresh(application)

        # Завантажуємо пакет для відповіді, якщо він есть
        if application.package_id:
            application = db.query(models.QuoteApplication).options(
                joinedload(models.QuoteApplication.package)
            ).filter(models.QuoteApplication.id == application.id).first()

        logger.info(f"Quote application created: {application.email} with package_id: {application.package_id}")

        # TODO: Додати відправку email в background task
        # background_tasks.add_task(send_quote_application_notification, application)

        return application

    except Exception as e:
        logger.error(f"Error creating quote application: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create application")


@router.post("/applications/consultation", response_model=schemas.ConsultationApplication)
async def create_consultation_application(
        application_data: schemas.ConsultationApplicationCreate,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    """Створити заявку на консультацію."""
    try:
        application = models.ConsultationApplication(**application_data.dict())
        db.add(application)
        db.commit()
        db.refresh(application)

        logger.info(f"Consultation application created: {application.first_name} {application.last_name}")

        # TODO: Додати відправку email в background task
        # background_tasks.add_task(send_consultation_application_notification, application)

        return application
    except Exception as e:
        logger.error(f"Error creating consultation application: {e}")
        raise HTTPException(status_code=500, detail="Failed to create application")


@router.get("/applications/quote", response_model=List[schemas.QuoteApplication])
async def get_quote_applications(
        status: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Отримати заявки на прорахунок (тільки адмін)."""
    query = db.query(models.QuoteApplication).options(
        joinedload(models.QuoteApplication.package)
    )

    if status:
        query = query.filter(models.QuoteApplication.status == status)

    if search:
        search_filter = or_(
            models.QuoteApplication.name.ilike(f"%{search}%"),
            models.QuoteApplication.email.ilike(f"%{search}%"),
            models.QuoteApplication.project_type.ilike(f"%{search}%"),
            models.QuoteApplication.description.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)

    applications = query.order_by(desc(models.QuoteApplication.created_at)).offset(skip).limit(limit).all()
    return applications


@router.get("/applications/consultation", response_model=List[schemas.ConsultationApplication])
async def get_consultation_applications(
        status: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Отримати заявки на консультацію (тільки адмін)."""
    query = db.query(models.ConsultationApplication)

    if status:
        query = query.filter(models.ConsultationApplication.status == status)

    if search:
        search_filter = or_(
            models.ConsultationApplication.first_name.ilike(f"%{search}%"),
            models.ConsultationApplication.last_name.ilike(f"%{search}%"),
            models.ConsultationApplication.phone.ilike(f"%{search}%"),
            models.ConsultationApplication.telegram.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)

    applications = query.order_by(desc(models.ConsultationApplication.created_at)).offset(skip).limit(limit).all()
    return applications


@router.get("/applications/quote/{application_id}", response_model=schemas.QuoteApplication)
async def get_quote_application(
        application_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Отримати заявку на прорахунок за ID (тільки адмін)."""
    application = db.query(models.QuoteApplication).options(
        joinedload(models.QuoteApplication.package)
    ).filter(models.QuoteApplication.id == application_id).first()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    return application


@router.put("/applications/quote/{application_id}", response_model=schemas.QuoteApplication)
async def update_quote_application(
        application_id: int,
        application_data: schemas.QuoteApplicationUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити статус заявки на прорахунок (тільки адмін)."""
    application = db.query(models.QuoteApplication).filter(
        models.QuoteApplication.id == application_id
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    old_status = application.status
    application.status = application_data.status.value

    if application_data.response_text:
        application.response_text = application_data.response_text

    if old_status != application_data.status.value:
        application.processed_at = datetime.utcnow()

    application.updated_at = datetime.utcnow()
    db.commit()

    # Завантажуємо з пакетом
    application = db.query(models.QuoteApplication).options(
        joinedload(models.QuoteApplication.package)
    ).filter(models.QuoteApplication.id == application_id).first()

    logger.info(f"Quote application {application_id} updated to {application_data.status} by {current_user.email}")
    return application


@router.put("/applications/consultation/{application_id}", response_model=schemas.ConsultationApplication)
async def update_consultation_application(
        application_id: int,
        application_data: schemas.ConsultationApplicationUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити статус заявки на консультацію (тільки адмін)."""
    application = db.query(models.ConsultationApplication).filter(
        models.ConsultationApplication.id == application_id
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    update_data = application_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status":
            setattr(application, field, value.value)
        else:
            setattr(application, field, value)

    application.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(application)

    logger.info(f"Consultation application {application_id} updated by {current_user.email}")
    return application


@router.delete("/applications/quote/{application_id}", response_model=schemas.Message)
async def delete_quote_application(
        application_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити заявку на прорахунок (тільки адмін)."""
    application = db.query(models.QuoteApplication).filter(
        models.QuoteApplication.id == application_id
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    db.delete(application)
    db.commit()

    logger.info(f"Quote application deleted: {application_id} by {current_user.email}")
    return {"message": "Application deleted successfully"}


@router.delete("/applications/consultation/{application_id}", response_model=schemas.Message)
async def delete_consultation_application(
        application_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити заявку на консультацію (тільки адмін)."""
    application = db.query(models.ConsultationApplication).filter(
        models.ConsultationApplication.id == application_id
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    db.delete(application)
    db.commit()

    logger.info(f"Consultation application deleted: {application_id} by {current_user.email}")
    return {"message": "Application deleted successfully"}


# ============ УНИВЕРСАЛЬНЫЕ АДМИНСКИЕ УТИЛИТЫ ============

def check_database_connection() -> bool:
    """Проверить соединение с базой данных."""
    try:
        from database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.post("/admin/flush-cache", response_model=schemas.Message)
async def flush_admin_cache(
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Очистить кеш админки."""
    try:
        # Очищаем сессии пользователей
        from auth import user_sessions
        user_sessions.clear()

        logger.info(f"Admin cache flushed by {current_user.email}")
        return {"message": "Cache flushed successfully"}
    except Exception as e:
        logger.error(f"Error flushing cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to flush cache")


@router.get("/admin/debug-info", response_model=Dict[str, Any])
async def get_admin_debug_info(
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Получить отладочную информацию для админки."""
    try:
        info = {
            "database_connection": check_database_connection(),
            "total_queries_count": db.query(models.Design).count() + db.query(models.Package).count(),
            "contact_info_exists": db.query(models.ContactInfo).first() is not None,
            "categories_count": db.query(models.DesignCategory).count(),
            "admin_user": {
                "id": current_user.id,
                "email": current_user.email,
                "is_admin": current_user.is_admin
            }
        }
        return info
    except Exception as e:
        logger.error(f"Error getting debug info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get debug info")


@router.patch("/admin/fix-database", response_model=schemas.Message)
async def fix_database_issues(
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Исправить проблемы с базой данных."""
    try:
        fixes_applied = []

        # Проверяем и создаем контактную информацию если не существует
        if not db.query(models.ContactInfo).first():
            contact_info = models.ContactInfo()
            db.add(contact_info)
            fixes_applied.append("Created empty contact_info record")

        # Проверяем существование базовых категорий
        basic_categories = ["all", "corporate", "e-commerce"]
        for cat_id in basic_categories:
            if not db.query(models.DesignCategory).filter(models.DesignCategory.id == cat_id).first():
                if cat_id == "all":
                    category = models.DesignCategory(
                        id="all",
                        slug="all",
                        name_uk="Всі проекти",
                        name_en="All Projects"
                    )
                    db.add(category)
                    fixes_applied.append(f"Created category: {cat_id}")

        db.commit()

        logger.info(f"Database fixes applied by {current_user.email}: {fixes_applied}")
        return {"message": f"Applied {len(fixes_applied)} fixes: {', '.join(fixes_applied)}"}

    except Exception as e:
        logger.error(f"Error fixing database: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to fix database issues")


# ============ КОНТЕНТ ============

@router.get("/content", response_model=List[schemas.Content])
async def get_all_content(
        active_only: bool = True,
        db: Session = Depends(get_db)
):
    """Отримати весь контент."""
    query = db.query(models.Content)

    if active_only:
        query = query.filter(models.Content.is_active == True)

    content = query.all()
    return content


@router.get("/content/{key}", response_model=schemas.Content)
async def get_content_by_key(key: str, db: Session = Depends(get_db)):
    """Отримати контент за ключем."""
    content = db.query(models.Content).filter(
        models.Content.key == key,
        models.Content.is_active == True
    ).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return content


@router.post("/content", response_model=schemas.Content)
async def create_content(
        content_data: schemas.ContentCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити новий контент (тільки адмін)."""
    # Перевіряємо чи вже існує контент з таким ключем
    existing = db.query(models.Content).filter(models.Content.key == content_data.key).first()
    if existing:
        raise HTTPException(status_code=400, detail="Content with this key already exists")

    content = models.Content(**content_data.dict())
    db.add(content)
    db.commit()
    db.refresh(content)

    logger.info(f"Content created: {content.key} by {current_user.email}")
    return content


@router.put("/content/{key}", response_model=schemas.Content)
async def update_content(
        key: str,
        content_data: schemas.ContentUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити контент (тільки адмін)."""
    content = db.query(models.Content).filter(models.Content.key == key).first()
    if not content:
        # Створюємо новий контент якщо не існує
        content = models.Content(
            key=key,
            content_uk=content_data.content_uk,
            content_en=content_data.content_en,
            description=content_data.description,
            is_active=content_data.is_active if hasattr(content_data, 'is_active') else True
        )
        db.add(content)
        logger.info(f"Content created: {key} by {current_user.email}")
    else:
        update_data = content_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(content, field, value)
        content.updated_at = datetime.utcnow()
        logger.info(f"Content updated: {key} by {current_user.email}")

    db.commit()
    db.refresh(content)
    return content


@router.delete("/content/{key}", response_model=schemas.Message)
async def delete_content(
        key: str,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити контент (тільки адмін)."""
    content = db.query(models.Content).filter(models.Content.key == key).first()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    db.delete(content)
    db.commit()

    logger.info(f"Content deleted: {key} by {current_user.email}")
    return {"message": "Content deleted successfully"}


# ============ КОНТАКТНА ІНФОРМАЦІЯ (КРИТИЧНО ИСПРАВЛЕНО) ============

@router.get("/contact-info", response_model=schemas.ContactInfo)
async def get_contact_info(db: Session = Depends(get_db)):
    """Отримати контактну інформацію."""
    try:
        contact_info = db.query(models.ContactInfo).first()
        if not contact_info:
            # Створюємо порожній запис якщо не існує
            contact_info = models.ContactInfo()
            db.add(contact_info)
            db.commit()
            db.refresh(contact_info)
            logger.info("Created empty contact info record")
        return contact_info
    except Exception as e:
        logger.error(f"Error fetching contact info: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch contact info")


@router.put("/contact-info", response_model=schemas.ContactInfo)
async def update_contact_info(
        contact_data: schemas.ContactInfoUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити контактну інформацію (тільки адмін) - КРИТИЧНО ИСПРАВЛЕНО."""
    try:
        contact_info = db.query(models.ContactInfo).first()

        if not contact_info:
            # Создаем новую запись если не существует
            contact_data_dict = contact_data.dict(exclude_unset=True, exclude_none=True)
            contact_info = models.ContactInfo(**contact_data_dict)
            db.add(contact_info)
            logger.info(f"Contact info created by {current_user.email}")
        else:
            # ИСПРАВЛЕНИЕ: Принудительно обновляем каждое поле
            update_data = contact_data.dict(exclude_unset=True, exclude_none=True)

            for field, value in update_data.items():
                if hasattr(contact_info, field):
                    setattr(contact_info, field, value)
                    logger.debug(f"Updated field {field} = {value}")
                else:
                    logger.warning(f"Field {field} not found in ContactInfo model")

            contact_info.updated_at = datetime.utcnow()
            logger.info(f"Contact info updated by {current_user.email}")

        # КРИТИЧНО: Принудительно сохраняем изменения
        db.flush()  # Применяем изменения к объекту
        db.commit()  # Сохраняем в БД
        db.refresh(contact_info)  # Обновляем объект из БД

        # Проверяем что данные действительно сохранились
        saved_contact_info = db.query(models.ContactInfo).first()
        logger.info(f"✅ Contact info saved: phone={saved_contact_info.phone}, email={saved_contact_info.email}")

        return saved_contact_info

    except Exception as e:
        logger.error(f"❌ Error updating contact info: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update contact info: {str(e)}")


# ============ SEO НАЛАШТУВАННЯ ============

@router.get("/seo", response_model=List[schemas.SEOSettings])
async def get_all_seo_settings(db: Session = Depends(get_db)):
    """Отримати всі SEO налаштування."""
    seo_settings = db.query(models.SEOSettings).all()
    return seo_settings


@router.get("/seo/{page}", response_model=schemas.SEOSettings)
async def get_seo_by_page(page: str, db: Session = Depends(get_db)):
    """Отримати SEO налаштування для сторінки."""
    seo = db.query(models.SEOSettings).filter(models.SEOSettings.page == page).first()
    if not seo:
        # Створюємо порожній запис
        seo = models.SEOSettings(page=page)
        db.add(seo)
        db.commit()
        db.refresh(seo)
    return seo


@router.post("/seo", response_model=schemas.SEOSettings)
async def create_seo_settings(
        seo_data: schemas.SEOSettingsCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити SEO налаштування (тільки адмін)."""
    existing = db.query(models.SEOSettings).filter(models.SEOSettings.page == seo_data.page).first()
    if existing:
        raise HTTPException(status_code=400, detail="SEO settings for this page already exist")

    seo = models.SEOSettings(**seo_data.dict())
    db.add(seo)
    db.commit()
    db.refresh(seo)

    logger.info(f"SEO settings created for page: {seo.page} by {current_user.email}")
    return seo


@router.put("/seo/{page}", response_model=schemas.SEOSettings)
async def update_seo_settings(
        page: str,
        seo_data: schemas.SEOSettingsUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити SEO налаштування (тільки адмін)."""
    seo = db.query(models.SEOSettings).filter(models.SEOSettings.page == page).first()
    if not seo:
        seo_dict = seo_data.dict(exclude_unset=True)
        seo_dict['page'] = page
        seo = models.SEOSettings(**seo_dict)
        db.add(seo)
        logger.info(f"SEO settings created for page: {page} by {current_user.email}")
    else:
        update_data = seo_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(seo, field, value)
        seo.updated_at = datetime.utcnow()
        logger.info(f"SEO settings updated for page: {page} by {current_user.email}")

    db.commit()
    db.refresh(seo)
    return seo


# ============ ПОЛІТИКИ ============

@router.get("/policies", response_model=List[schemas.Policy])
async def get_policies(
        active_only: bool = True,
        db: Session = Depends(get_db)
):
    """Отримати всі політики."""
    query = db.query(models.Policy)

    if active_only:
        query = query.filter(models.Policy.is_active == True)

    policies = query.all()
    return policies


@router.get("/policies/{policy_type}", response_model=schemas.Policy)
async def get_policy(policy_type: str, db: Session = Depends(get_db)):
    """Отримати політику за типом."""
    policy = db.query(models.Policy).filter(
        models.Policy.type == policy_type,
        models.Policy.is_active == True
    ).first()
    if not policy:
        # Створюємо порожню політику
        policy = models.Policy(type=policy_type)
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


@router.post("/policies", response_model=schemas.Policy)
async def create_policy(
        policy_data: schemas.PolicyCreate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Створити політику (тільки адмін)."""
    existing = db.query(models.Policy).filter(models.Policy.type == policy_data.type).first()
    if existing:
        raise HTTPException(status_code=400, detail="Policy of this type already exists")

    policy = models.Policy(**policy_data.dict())
    db.add(policy)
    db.commit()
    db.refresh(policy)

    logger.info(f"Policy created: {policy.type} by {current_user.email}")
    return policy


@router.put("/policies/{policy_type}", response_model=schemas.Policy)
async def update_policy(
        policy_type: str,
        policy_data: schemas.PolicyUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити політику (тільки адмін)."""
    policy = db.query(models.Policy).filter(models.Policy.type == policy_type).first()
    if not policy:
        policy_dict = policy_data.dict(exclude_unset=True)
        policy_dict['type'] = policy_type
        policy = models.Policy(**policy_dict)
        db.add(policy)
        logger.info(f"Policy created: {policy_type} by {current_user.email}")
    else:
        update_data = policy_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(policy, field, value)
        policy.updated_at = datetime.utcnow()
        logger.info(f"Policy updated: {policy_type} by {current_user.email}")

    db.commit()
    db.refresh(policy)
    return policy


# ============ ЗАВАНТАЖЕННЯ ФАЙЛІВ ============

@router.post("/upload", response_model=schemas.UploadedFile)
async def upload_file(
        file: UploadFile = File(...),
        alt_text: Optional[str] = Form(None),
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Завантажити файл (тільки адмін)."""
    # Перевіряємо розмір файлу
    if hasattr(file, 'size') and file.size and file.size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size {file.size} exceeds maximum allowed size {settings.MAX_FILE_SIZE} bytes"
        )

    # Перевіряємо розширення файлу
    file_extension = Path(file.filename).suffix.lower() if file.filename else ''
    if file_extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension {file_extension} is not allowed. Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    try:
        # Зберігаємо файл
        saved_file = await save_uploaded_file(file)

        # Зберігаємо інформацію в БД
        uploaded_file = models.UploadedFile(
            uploaded_by_id=current_user.id,
            original_filename=saved_file["original_name"],
            stored_filename=saved_file["name"],
            file_path=saved_file["path"],
            file_url=saved_file["url"],
            file_size=saved_file["size"],
            mime_type=saved_file["content_type"],
            file_extension=file_extension,
            category=saved_file["category"],
            hash=saved_file.get("hash"),
            alt_text=alt_text,
            thumbnail_url=saved_file.get("thumbnail_url")
        )

        db.add(uploaded_file)
        db.commit()
        db.refresh(uploaded_file)

        logger.info(f"File uploaded: {uploaded_file.original_filename} by {current_user.email}")
        return uploaded_file

    except Exception as e:
        logger.error(f"File upload error: {e}")
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")


@router.get("/files", response_model=List[schemas.UploadedFile])
async def get_uploaded_files(
        category: Optional[str] = None,
        used_only: Optional[bool] = None,
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Отримати список завантажених файлів (тільки адмін)."""
    query = db.query(models.UploadedFile)

    if category:
        query = query.filter(models.UploadedFile.category == category)

    if used_only is not None:
        query = query.filter(models.UploadedFile.is_used == used_only)

    files = query.order_by(desc(models.UploadedFile.created_at)).offset(skip).limit(limit).all()
    return files


@router.put("/files/{file_id}", response_model=schemas.UploadedFile)
async def update_uploaded_file(
        file_id: int,
        file_data: schemas.UploadedFileUpdate,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Оновити метаданні файлу (тільки адмін)."""
    file_record = db.query(models.UploadedFile).filter(models.UploadedFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    update_data = file_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(file_record, field, value)

    db.commit()
    db.refresh(file_record)

    logger.info(f"File metadata updated: {file_record.stored_filename} by {current_user.email}")
    return file_record


@router.delete("/files/{file_id}", response_model=schemas.Message)
async def delete_uploaded_file(
        file_id: int,
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Видалити завантажений файл (тільки адмін)."""
    file_record = db.query(models.UploadedFile).filter(models.UploadedFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # Видаляємо файл з диска
    file_deleted = delete_file(file_record.stored_filename)

    # Видаляємо запис з БД навіть якщо файл не вдалося видалити з диска
    file_name = file_record.stored_filename
    db.delete(file_record)
    db.commit()

    if not file_deleted:
        logger.warning(f"File removed from DB but not from disk: {file_name}")

    logger.info(f"File deleted: {file_name} by {current_user.email}")
    return {"message": "File deleted successfully"}


# ============ СТАТИСТИКА ДЛЯ АДМІНА ============

@router.get("/admin/stats", response_model=schemas.DashboardStats)
async def get_dashboard_stats(
        current_user: models.User = Depends(get_current_admin_user),
        db: Session = Depends(get_db)
):
    """Отримати статистику для дашборду (тільки адмін)."""
    try:
        # Основна статистика
        total_quote_apps = db.query(models.QuoteApplication).count()
        total_consultation_apps = db.query(models.ConsultationApplication).count()
        new_quote_apps = db.query(models.QuoteApplication).filter(
            models.QuoteApplication.status == "new"
        ).count()
        new_consultation_apps = db.query(models.ConsultationApplication).filter(
            models.ConsultationApplication.status == "new"
        ).count()
        total_reviews = db.query(models.Review).count()
        approved_reviews = db.query(models.Review).filter(models.Review.is_approved == True).count()
        pending_reviews = db.query(models.Review).filter(models.Review.is_approved == False).count()
        total_designs = db.query(models.Design).count()

        # Файлова статистика
        upload_stats = get_upload_stats()

        # Остання активність
        recent_activity = []

        # Останні заявки на прорахунок
        recent_quotes = db.query(models.QuoteApplication).order_by(
            desc(models.QuoteApplication.created_at)
        ).limit(5).all()

        for app in recent_quotes:
            recent_activity.append({
                "type": "quote_application",
                "message": f"New quote application from {app.name}",
                "timestamp": app.created_at.isoformat(),
                "id": app.id
            })

        # Останні заявки на консультацію
        recent_consultations = db.query(models.ConsultationApplication).order_by(
            desc(models.ConsultationApplication.created_at)
        ).limit(3).all()

        for app in recent_consultations:
            recent_activity.append({
                "type": "consultation_application",
                "message": f"New consultation request from {app.first_name} {app.last_name}",
                "timestamp": app.created_at.isoformat(),
                "id": app.id
            })

        # Нові відгуки
        recent_reviews = db.query(models.Review).filter(
            models.Review.is_approved == False
        ).order_by(desc(models.Review.created_at)).limit(3).all()

        for review in recent_reviews:
            recent_activity.append({
                "type": "review",
                "message": f"New review awaiting approval (rating: {review.rating}/5)",
                "timestamp": review.created_at.isoformat(),
                "id": review.id
            })

        # Сортуємо активність за часом
        recent_activity.sort(key=lambda x: x["timestamp"], reverse=True)
        recent_activity = recent_activity[:10]  # Показуємо тільки останні 10

        return schemas.DashboardStats(
            total_applications=total_quote_apps + total_consultation_apps,
            new_applications=new_quote_apps + new_consultation_apps,
            total_reviews=total_reviews,
            total_designs=total_designs,
            approved_reviews=approved_reviews,
            pending_reviews=pending_reviews,
            total_files=upload_stats.get("total_files", 0),
            total_file_size=upload_stats.get("total_size", 0),
            recent_activity=recent_activity
        )
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard statistics")


# ============ ПОШУК ============

@router.post("/search", response_model=schemas.SearchResponse)
async def search_content(
        search_data: schemas.SearchRequest,
        db: Session = Depends(get_db)
):
    """Пошук по контенту сайту."""
    try:
        import time
        start_time = time.time()

        results = []
        query = search_data.query.strip()

        if not query:
            return schemas.SearchResponse(
                results=[],
                total=0,
                query=query,
                took=0.0
            )

        # Пошук по дизайнах
        design_query = db.query(models.Design).filter(
            models.Design.is_published == True
        )

        if search_data.category and search_data.category != "all":
            design_query = design_query.filter(models.Design.category_id == search_data.category)

        designs = design_query.filter(
            or_(
                models.Design.title.ilike(f"%{query}%"),
                models.Design.description_uk.ilike(f"%{query}%"),
                models.Design.description_en.ilike(f"%{query}%"),
                models.Design.technology.ilike(f"%{query}%")
            )
        ).limit(search_data.limit).all()

        for design in designs:
            results.append(schemas.SearchResult(
                type="design",
                id=design.id,
                title=design.title,
                description=design.description_uk[:100] + "..." if len(
                    design.description_uk) > 100 else design.description_uk,
                url=f"/designs/{design.slug or design.id}",
                image=design.image_url,
                relevance=1.0  # Можна додати більш складний алгоритм релевантності
            ))

        # Пошук по пакетах
        if not search_data.category or search_data.category == "packages":
            packages = db.query(models.Package).filter(
                models.Package.is_active == True,
                or_(
                    models.Package.name.ilike(f"%{query}%"),
                    models.Package.features_uk.ilike(f"%{query}%") if models.Package.features_uk else False,
                    models.Package.features_en.ilike(f"%{query}%") if models.Package.features_en else False
                )
            ).limit(search_data.limit).all()

            for package in packages:
                results.append(schemas.SearchResult(
                    type="package",
                    id=package.id,
                    title=package.name,
                    description=f"Price: {package.price_uk}",
                    url=f"/packages/{package.slug or package.id}",
                    relevance=0.8
                ))

        # Обмежуємо результати
        total_results = len(results)
        results = results[search_data.offset:search_data.offset + search_data.limit]

        elapsed_time = (time.time() - start_time) * 1000  # в мілісекундах

        return schemas.SearchResponse(
            results=results,
            total=total_results,
            query=query,
            took=round(elapsed_time, 2)
        )

    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail="Search failed")


# ============ ПУБЛІЧНІ НАЛАШТУВАННЯ ============

@router.get("/config", response_model=Dict[str, Any])
async def get_public_config(db: Session = Depends(get_db)):
    """Отримати публічну конфігурацію для фронтенду."""
    try:
        # Основна конфігурація
        config = {
            "app_name": settings.APP_NAME,
            "version": settings.VERSION,
            "max_file_size": settings.MAX_FILE_SIZE,
            "allowed_extensions": settings.ALLOWED_EXTENSIONS,
            "debug": settings.DEBUG
        }

        # Додаємо публічні налаштування з БД
        try:
            public_settings = db.query(models.SiteSettings).filter(
                models.SiteSettings.is_public == True
            ).all()

            settings_dict = {}
            for setting in public_settings:
                if setting.value:
                    if setting.key == "maintenance_mode":
                        settings_dict[setting.key] = setting.value.lower() in ('true', '1', 'yes')
                    else:
                        settings_dict[setting.key] = setting.value

            config["settings"] = settings_dict
        except Exception:
            config["settings"] = {}

        return config

    except Exception as e:
        logger.error(f"Error getting public config: {e}")
        return {
            "app_name": settings.APP_NAME,
            "version": settings.VERSION,
            "debug": settings.DEBUG
        }


# ============ HEALTH CHECK ============

@router.get("/health", response_model=Dict[str, Any])
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Перевіряємо з'єднання з БД
        db.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": settings.VERSION,
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": settings.VERSION,
            "database": "disconnected",
            "error": str(e)
        }