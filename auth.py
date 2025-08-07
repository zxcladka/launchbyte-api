from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import secrets
import string
import logging

from database import get_db
import models
from config import settings

# Налаштування логування
logger = logging.getLogger(__name__)

# Налаштування для хешування паролів
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # Підвищуємо безпеку
)

# Налаштування JWT токенів
security = HTTPBearer(auto_error=False)

# Кеш для сесій користувачів
user_sessions: Dict[str, Dict[str, Any]] = {}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Перевіряє пароль з хешем."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Створює хеш пароля."""
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Password hashing error: {e}")
        raise HTTPException(status_code=500, detail="Password hashing failed")


def generate_secure_password(length: int = 16) -> str:
    """Генерує безпечний пароль."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Створює JWT токен."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })

    try:
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"JWT encoding error: {e}")
        raise HTTPException(status_code=500, detail="Token creation failed")


def create_refresh_token(data: dict) -> str:
    """Створює refresh токен."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=30)  # 30 днів для refresh токену

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })

    try:
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Refresh token creation error: {e}")
        raise HTTPException(status_code=500, detail="Refresh token creation failed")


def verify_token(token: str) -> Optional[dict]:
    """Перевіряє JWT токен."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        # Перевіряємо тип токену
        token_type = payload.get("type", "access")
        if token_type not in ["access", "refresh"]:
            logger.warning(f"Invalid token type: {token_type}")
            return None

        # Перевіряємо термін дії
        exp = payload.get("exp")
        if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
            logger.info("Token expired")
            return None

        return payload
    except jwt.ExpiredSignatureError:
        logger.info("Token signature expired")
        return None
    except JWTError as e:
        logger.warning(f"JWT verification error: {e}")
        return None
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None


def blacklist_token(token: str, reason: str = "logout"):
    """Додає токен в чорний список."""
    # В продакшн середовищі це мало б зберігатися в Redis
    # Для спрощення використовуємо in-memory словник
    payload = verify_token(token)
    if payload:
        jti = payload.get("jti") or token[:32]  # Використовуємо jti або початок токену як ID
        user_sessions[jti] = {
            "blacklisted": True,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Token blacklisted: {reason}")


def is_token_blacklisted(token: str) -> bool:
    """Перевіряє чи токен в чорному списку."""
    payload = verify_token(token)
    if not payload:
        return True

    jti = payload.get("jti") or token[:32]
    return user_sessions.get(jti, {}).get("blacklisted", False)


def set_auth_cookie(response: Response, token: str, refresh_token: Optional[str] = None) -> None:
    """Встановлює токен у cookie."""
    # Access token cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        max_age=settings.COOKIE_MAX_AGE,
        expires=settings.COOKIE_MAX_AGE,
        path="/",
        domain=None,
        secure=settings.COOKIE_SECURE,
        httponly=settings.COOKIE_HTTPONLY,
        samesite=settings.COOKIE_SAMESITE,
    )

    # Refresh token cookie (якщо надано)
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=f"Bearer {refresh_token}",
            max_age=30 * 24 * 60 * 60,  # 30 днів
            path="/api/v1/auth/refresh",  # Обмежуємо шлях
            domain=None,
            secure=settings.COOKIE_SECURE,
            httponly=True,  # Завжди httponly для refresh токену
            samesite=settings.COOKIE_SAMESITE,
        )


def clear_auth_cookie(response: Response) -> None:
    """Очищає токен з cookie."""
    response.delete_cookie(
        key="access_token",
        path="/",
        domain=None,
        secure=settings.COOKIE_SECURE,
        httponly=settings.COOKIE_HTTPONLY,
        samesite=settings.COOKIE_SAMESITE,
    )

    response.delete_cookie(
        key="refresh_token",
        path="/api/v1/auth/refresh",
        domain=None,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


def get_token_from_cookie_or_header(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    """Отримує токен з cookie або header."""
    token = None

    # Спочатку перевіряємо header (має пріоритет)
    if credentials and credentials.credentials:
        token = credentials.credentials

    # Якщо в header немає, перевіряємо cookie
    if not token:
        cookie_token = request.cookies.get("access_token")
        if cookie_token and cookie_token.startswith("Bearer "):
            token = cookie_token[7:]  # Прибираємо "Bearer "

    return token


def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    """Аутентифікує користувача."""
    try:
        user = db.query(models.User).filter(models.User.email == email.lower().strip()).first()
        if not user:
            logger.info(f"User not found: {email}")
            return None

        if not verify_password(password, user.hashed_password):
            logger.info(f"Invalid password for user: {email}")
            return None

        # Оновлюємо час останнього входу
        user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"User authenticated successfully: {email}")
        return user
    except Exception as e:
        logger.error(f"Authentication error for {email}: {e}")
        return None


def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: Session = Depends(get_db)
) -> models.User:
    """Отримує поточного користувача з JWT токена."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = get_token_from_cookie_or_header(request, credentials)

    if not token:
        raise credentials_exception

    # Перевіряємо чи токен не в чорному списку
    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_token(token)
        if payload is None:
            raise credentials_exception

        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception

        # Перевіряємо тип токену
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

    except Exception as e:
        logger.warning(f"Token validation error: {e}")
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        logger.warning(f"User not found in database: {email}")
        raise credentials_exception

    return user


def get_current_active_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    """Перевіряє що користувач активний."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )
    return current_user


def get_current_admin_user(current_user: models.User = Depends(get_current_active_user)) -> models.User:
    """Перевіряє що користувач є адміністратором."""
    if not current_user.is_admin:
        logger.warning(f"Non-admin user attempted admin action: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required"
        )
    return current_user


def get_current_user_optional(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: Session = Depends(get_db)
) -> Optional[models.User]:
    """Отримує поточного користувача (опціонально, без помилки якщо не авторизований)."""
    try:
        return get_current_user(request, credentials, db)
    except HTTPException:
        return None


def create_user(
        db: Session,
        email: str,
        name: str,
        password: str,
        is_admin: bool = False
) -> models.User:
    """Створює нового користувача."""
    try:
        # Нормалізуємо email
        email = email.lower().strip()

        # Перевіряємо чи користувач вже існує
        existing_user = db.query(models.User).filter(models.User.email == email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists"
            )

        # Валідуємо пароль
        if len(password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )

        # Створюємо користувача
        hashed_password = get_password_hash(password)
        user = models.User(
            email=email,
            name=name.strip(),
            hashed_password=hashed_password,
            is_admin=is_admin,
            is_active=True
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(f"User created successfully: {email}")
        return user

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating user {email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )


def change_password(db: Session, user: models.User, old_password: str, new_password: str) -> bool:
    """Змінює пароль користувача."""
    try:
        if not verify_password(old_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )

        if len(new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 6 characters long"
            )

        user.hashed_password = get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"Password changed for user: {user.email}")
        return True

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error changing password for {user.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )


def reset_password(db: Session, email: str, new_password: str) -> bool:
    """Скидає пароль користувача (тільки для адміна)."""
    try:
        user = db.query(models.User).filter(models.User.email == email.lower().strip()).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        if len(new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )

        user.hashed_password = get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"Password reset for user: {email}")
        return True

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error resetting password for {email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )


def update_user_profile(
        db: Session,
        user: models.User,
        name: Optional[str] = None,
        avatar: Optional[str] = None
) -> models.User:
    """Оновлює профіль користувача."""
    try:
        if name is not None:
            user.name = name.strip()
        if avatar is not None:
            user.avatar = avatar.strip() if avatar else None

        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)

        logger.info(f"Profile updated for user: {user.email}")
        return user

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating profile for {user.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )


def deactivate_user(db: Session, user_id: int) -> bool:
    """Деактивує користувача."""
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        if user.is_admin:
            # Перевіряємо чи є інші адміни
            admin_count = db.query(models.User).filter(
                models.User.is_admin == True,
                models.User.is_active == True,
                models.User.id != user_id
            ).count()

            if admin_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate the last active admin"
                )

        user.is_active = False
        user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"User deactivated: {user.email}")
        return True

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate user"
        )


def make_admin(db: Session, user_id: int) -> bool:
    """Робить користувача адміністратором."""
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        user.is_admin = True
        user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"User made admin: {user.email}")
        return True

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error making user admin {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to make user admin"
        )


def remove_admin(db: Session, user_id: int) -> bool:
    """Забирає права адміністратора."""
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Перевіряємо чи це не останній адмін
        admin_count = db.query(models.User).filter(
            models.User.is_admin == True,
            models.User.is_active == True,
            models.User.id != user_id
        ).count()

        if admin_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove admin rights from the last active admin"
            )

        user.is_admin = False
        user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"Admin rights removed from user: {user.email}")
        return True

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing admin rights {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove admin rights"
        )


def validate_admin_credentials(email: str, password: str) -> bool:
    """Перевіряє чи є правильні креденціали адміна з налаштувань."""
    try:
        return (
                email.lower().strip() == settings.ADMIN_EMAIL.lower() and
                verify_password(password, get_password_hash(settings.ADMIN_PASSWORD))
        )
    except Exception as e:
        logger.error(f"Error validating admin credentials: {e}")
        return False


def get_secure_admin_password() -> str:
    """Генерує безпечний пароль для адміна якщо він не встановлений."""
    if not settings.ADMIN_PASSWORD or "CHANGE" in settings.ADMIN_PASSWORD.upper():
        password = generate_secure_password(16)
        logger.warning(f"⚠️  Generated admin password: {password}")
        logger.warning("⚠️  Please set ADMIN_PASSWORD environment variable for production!")
        return password

    return settings.ADMIN_PASSWORD


def create_password_reset_token(email: str) -> str:
    """Створює токен для скидання пароля."""
    data = {
        "sub": email,
        "type": "password_reset"
    }

    expire = datetime.utcnow() + timedelta(hours=1)  # Токен діє 1 годину
    data.update({"exp": expire})

    try:
        token = jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        logger.info(f"Password reset token created for: {email}")
        return token
    except Exception as e:
        logger.error(f"Error creating password reset token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create reset token"
        )


def verify_password_reset_token(token: str) -> Optional[str]:
    """Перевіряє токен скидання пароля та повертає email."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        if payload.get("type") != "password_reset":
            return None

        email = payload.get("sub")
        return email
    except jwt.ExpiredSignatureError:
        logger.info("Password reset token expired")
        return None
    except JWTError as e:
        logger.warning(f"Invalid password reset token: {e}")
        return None


def get_user_permissions(user: models.User) -> Dict[str, bool]:
    """Отримує права користувача."""
    if user.is_admin:
        return {
            "can_view_admin": True,
            "can_create_designs": True,
            "can_edit_designs": True,
            "can_delete_designs": True,
            "can_manage_packages": True,
            "can_manage_users": True,
            "can_approve_reviews": True,
            "can_manage_content": True,
            "can_view_applications": True,
            "can_upload_files": True,
            "can_manage_settings": True
        }
    else:
        return {
            "can_view_admin": False,
            "can_create_designs": False,
            "can_edit_designs": False,
            "can_delete_designs": False,
            "can_manage_packages": False,
            "can_manage_users": False,
            "can_approve_reviews": False,
            "can_manage_content": False,
            "can_view_applications": False,
            "can_upload_files": False,
            "can_manage_settings": False,
            "can_leave_review": True,
            "can_submit_applications": True
        }


def log_user_activity(
        user: models.User,
        action: str,
        details: Optional[str] = None,
        ip_address: Optional[str] = None
):
    """Логує активність користувача."""
    log_data = {
        "user_id": user.id,
        "email": user.email,
        "action": action,
        "timestamp": datetime.utcnow().isoformat(),
        "ip_address": ip_address,
        "details": details
    }

    # В продакшн середовищі це мало б зберігатися в окремій таблиці або сервісі логування
    logger.info(f"User activity: {log_data}")


def cleanup_expired_sessions():
    """Очищує застарілі сесії."""
    current_time = datetime.utcnow()
    cleaned_count = 0

    for jti, session_data in list(user_sessions.items()):
        if "timestamp" in session_data:
            try:
                session_time = datetime.fromisoformat(session_data["timestamp"])
                if current_time - session_time > timedelta(days=7):  # Старі сесії більше тижня
                    del user_sessions[jti]
                    cleaned_count += 1
            except:
                # Видаляємо некоректні записи
                del user_sessions[jti]
                cleaned_count += 1

    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} expired sessions")


def validate_password_strength(password: str) -> Dict[str, Any]:
    """Перевіряє силу пароля."""
    result = {
        "is_strong": True,
        "score": 0,
        "suggestions": []
    }

    if len(password) < 8:
        result["is_strong"] = False
        result["suggestions"].append("Password should be at least 8 characters long")
    else:
        result["score"] += 25

    if not any(c.islower() for c in password):
        result["is_strong"] = False
        result["suggestions"].append("Password should contain lowercase letters")
    else:
        result["score"] += 25

    if not any(c.isupper() for c in password):
        result["is_strong"] = False
        result["suggestions"].append("Password should contain uppercase letters")
    else:
        result["score"] += 25

    if not any(c.isdigit() for c in password):
        result["is_strong"] = False
        result["suggestions"].append("Password should contain numbers")
    else:
        result["score"] += 25

    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        result["suggestions"].append("Password should contain special characters for extra security")
    else:
        result["score"] += 10  # Бонус за спеціальні символи

    return result