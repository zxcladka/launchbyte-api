import smtplib
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.utils import formataddr
from typing import List, Optional, Dict, Any, Union
import logging
from datetime import datetime
import asyncio
from pathlib import Path
import json

from config import settings
from database import get_db_session
import models

logger = logging.getLogger(__name__)


class EmailTemplate:
    """Клас для роботи з email шаблонами."""

    def __init__(self, name: str, subject_uk: str, subject_en: str,
                 content_uk: str, content_en: str, variables: Optional[List[str]] = None):
        self.name = name
        self.subject_uk = subject_uk
        self.subject_en = subject_en
        self.content_uk = content_uk
        self.content_en = content_en
        self.variables = variables or []

    def render(self, language: str = "uk", **kwargs) -> tuple[str, str]:
        """Рендерить шаблон з переданими змінними."""
        subject = self.subject_uk if language == "uk" else self.subject_en
        content = self.content_uk if language == "uk" else self.content_en

        # Замінюємо змінні
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            subject = subject.replace(placeholder, str(value))
            content = content.replace(placeholder, str(value))

        return subject, content


class EmailService:
    """Сервіс для відправки email повідомлень."""

    def __init__(self):
        self.smtp_server = settings.SMTP_SERVER
        self.smtp_port = settings.SMTP_PORT
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.use_tls = settings.SMTP_USE_TLS
        self.use_ssl = settings.SMTP_USE_SSL
        self.from_email = settings.FROM_EMAIL

        # Завантажуємо шаблони
        self.templates = self._load_default_templates()

    def _load_default_templates(self) -> Dict[str, EmailTemplate]:
        """Завантажує стандартні шаблони email."""
        return {
            "quote_application": EmailTemplate(
                name="quote_application",
                subject_uk="Нова заявка на прорахунок проекту",
                subject_en="New Quote Application",
                content_uk="""
                <h2>Нова заявка на прорахунок проекту</h2>
                <p><strong>Ім'я:</strong> {name}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Телефон:</strong> {phone}</p>
                <p><strong>Тип проекту:</strong> {project_type}</p>
                <p><strong>Бюджет:</strong> {budget}</p>
                <p><strong>Опис проекту:</strong></p>
                <p>{description}</p>
                {package_info}
                <p><strong>Дата подання:</strong> {created_at}</p>
                """,
                content_en="""
                <h2>New Quote Application</h2>
                <p><strong>Name:</strong> {name}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Phone:</strong> {phone}</p>
                <p><strong>Project Type:</strong> {project_type}</p>
                <p><strong>Budget:</strong> {budget}</p>
                <p><strong>Project Description:</strong></p>
                <p>{description}</p>
                {package_info}
                <p><strong>Submitted at:</strong> {created_at}</p>
                """,
                variables=["name", "email", "phone", "project_type", "budget", "description", "package_info",
                           "created_at"]
            ),

            "consultation_application": EmailTemplate(
                name="consultation_application",
                subject_uk="Нова заявка на консультацію",
                subject_en="New Consultation Request",
                content_uk="""
                <h2>Нова заявка на консультацію</h2>
                <p><strong>Ім'я:</strong> {first_name} {last_name}</p>
                <p><strong>Телефон:</strong> {phone}</p>
                <p><strong>Telegram:</strong> {telegram}</p>
                <p><strong>Повідомлення:</strong></p>
                <p>{message}</p>
                <p><strong>Дата подання:</strong> {created_at}</p>
                """,
                content_en="""
                <h2>New Consultation Request</h2>
                <p><strong>Name:</strong> {first_name} {last_name}</p>
                <p><strong>Phone:</strong> {phone}</p>
                <p><strong>Telegram:</strong> {telegram}</p>
                <p><strong>Message:</strong></p>
                <p>{message}</p>
                <p><strong>Submitted at:</strong> {created_at}</p>
                """,
                variables=["first_name", "last_name", "phone", "telegram", "message", "created_at"]
            ),

            "quote_confirmation": EmailTemplate(
                name="quote_confirmation",
                subject_uk="Ваша заявка отримана - WebCraft Pro",
                subject_en="Your Quote Request Received - WebCraft Pro",
                content_uk="""
                <h2>Дякуємо за вашу заявку!</h2>
                <p>Вітаю, {name}!</p>
                <p>Ми отримали вашу заявку на прорахунок проекту <strong>"{project_type}"</strong>.</p>
                <p>Наша команда розгляне ваш запит і зв'яжеться з вами найближчим часом для обговорення деталей проекту.</p>

                <h3>Деталі вашої заявки:</h3>
                <ul>
                    <li><strong>Тип проекту:</strong> {project_type}</li>
                    <li><strong>Бюджет:</strong> {budget}</li>
                    <li><strong>Контактний телефон:</strong> {phone}</li>
                </ul>

                <p>Якщо у вас виникнуть питання, не соромтеся звертатися:</p>
                <ul>
                    <li>Email: {support_email}</li>
                    <li>Телефон: {support_phone}</li>
                    <li>Telegram: {support_telegram}</li>
                </ul>

                <p>З повагою,<br>Команда WebCraft Pro</p>
                """,
                content_en="""
                <h2>Thank you for your request!</h2>
                <p>Hello {name}!</p>
                <p>We have received your quote request for <strong>"{project_type}"</strong> project.</p>
                <p>Our team will review your request and contact you soon to discuss project details.</p>

                <h3>Your Request Details:</h3>
                <ul>
                    <li><strong>Project Type:</strong> {project_type}</li>
                    <li><strong>Budget:</strong> {budget}</li>
                    <li><strong>Contact Phone:</strong> {phone}</li>
                </ul>

                <p>If you have any questions, don't hesitate to contact us:</p>
                <ul>
                    <li>Email: {support_email}</li>
                    <li>Phone: {support_phone}</li>
                    <li>Telegram: {support_telegram}</li>
                </ul>

                <p>Best regards,<br>WebCraft Pro Team</p>
                """,
                variables=["name", "project_type", "budget", "phone", "support_email", "support_phone",
                           "support_telegram"]
            ),

            "consultation_confirmation": EmailTemplate(
                name="consultation_confirmation",
                subject_uk="Ваша заявка на консультацію отримана - WebCraft Pro",
                subject_en="Your Consultation Request Received - WebCraft Pro",
                content_uk="""
                <h2>Дякуємо за звернення!</h2>
                <p>Вітаю, {first_name}!</p>
                <p>Ми отримали вашу заявку на безкоштовну консультацію.</p>
                <p>Наш спеціаліст зв'яжеться з вами найближчим часом за вказаними контактними даними.</p>

                <h3>Ваші контактні дані:</h3>
                <ul>
                    <li><strong>Телефон:</strong> {phone}</li>
                    <li><strong>Telegram:</strong> {telegram}</li>
                </ul>

                <p>Під час консультації ми обговоримо:</p>
                <ul>
                    <li>Ваші потреби та цілі</li>
                    <li>Можливі рішення</li>
                    <li>Терміни та вартість</li>
                    <li>Наступні кроки</li>
                </ul>

                <p>З повагою,<br>Команда WebCraft Pro</p>
                """,
                content_en="""
                <h2>Thank you for contacting us!</h2>
                <p>Hello {first_name}!</p>
                <p>We have received your request for a free consultation.</p>
                <p>Our specialist will contact you soon using the provided contact information.</p>

                <h3>Your Contact Information:</h3>
                <ul>
                    <li><strong>Phone:</strong> {phone}</li>
                    <li><strong>Telegram:</strong> {telegram}</li>
                </ul>

                <p>During the consultation we will discuss:</p>
                <ul>
                    <li>Your needs and goals</li>
                    <li>Possible solutions</li>
                    <li>Timeline and cost</li>
                    <li>Next steps</li>
                </ul>

                <p>Best regards,<br>WebCraft Pro Team</p>
                """,
                variables=["first_name", "phone", "telegram"]
            ),

            "review_moderation": EmailTemplate(
                name="review_moderation",
                subject_uk="Новий відгук потребує модерації",
                subject_en="New Review Requires Moderation",
                content_uk="""
                <h2>Новий відгук на модерацію</h2>
                <p><strong>Автор:</strong> {author_name} ({author_email})</p>
                <p><strong>Компанія:</strong> {company}</p>
                <p><strong>Рейтинг:</strong> {rating}/5</p>

                <h3>Текст відгуку:</h3>
                <div style="background: #f5f5f5; padding: 15px; border-left: 4px solid #007bff;">
                    {review_text}
                </div>

                <p><strong>Дата написання:</strong> {created_at}</p>

                <p><a href="{admin_url}/reviews/{review_id}">Переглянути в адмін-панелі</a></p>
                """,
                content_en="""
                <h2>New Review for Moderation</h2>
                <p><strong>Author:</strong> {author_name} ({author_email})</p>
                <p><strong>Company:</strong> {company}</p>
                <p><strong>Rating:</strong> {rating}/5</p>

                <h3>Review Text:</h3>
                <div style="background: #f5f5f5; padding: 15px; border-left: 4px solid #007bff;">
                    {review_text}
                </div>

                <p><strong>Date:</strong> {created_at}</p>

                <p><a href="{admin_url}/reviews/{review_id}">View in Admin Panel</a></p>
                """,
                variables=["author_name", "author_email", "company", "rating", "review_text", "created_at", "admin_url",
                           "review_id"]
            ),

            "password_reset": EmailTemplate(
                name="password_reset",
                subject_uk="Скидання пароля - WebCraft Pro",
                subject_en="Password Reset - WebCraft Pro",
                content_uk="""
                <h2>Скидання пароля</h2>
                <p>Ви отримали цей лист, тому що був запит на скидання пароля для вашого акаунту.</p>

                <p>Для скидання пароля перейдіть за посиланням нижче:</p>
                <p><a href="{reset_url}" style="display: inline-block; background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Скинути пароль</a></p>

                <p>Посилання дійсне протягом 1 години.</p>

                <p>Якщо ви не запитували скидання пароля, проігноруйте цей лист.</p>

                <p>З повагою,<br>Команда WebCraft Pro</p>
                """,
                content_en="""
                <h2>Password Reset</h2>
                <p>You are receiving this email because a password reset was requested for your account.</p>

                <p>To reset your password, click the link below:</p>
                <p><a href="{reset_url}" style="display: inline-block; background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Reset Password</a></p>

                <p>This link is valid for 1 hour.</p>

                <p>If you did not request a password reset, please ignore this email.</p>

                <p>Best regards,<br>WebCraft Pro Team</p>
                """,
                variables=["reset_url"]
            )
        }

    def _create_message(self, to_email: str, subject: str, content: str,
                        from_name: str = "WebCraft Pro") -> MIMEMultipart:
        """Створює email повідомлення."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((from_name, self.from_email))
        msg["To"] = to_email

        # HTML частина
        html_part = MIMEText(content, "html", "utf-8")
        msg.attach(html_part)

        # Додаємо базовий CSS стиль
        styled_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{subject}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
                h1, h2, h3 {{ color: #007bff; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666; }}
                .button {{ display: inline-block; background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; }}
                .highlight {{ background: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; margin: 15px 0; }}
            </style>
        </head>
        <body>
            {content}
            <div class="footer">
                <p>Цей лист надіслано автоматично. Будь ласка, не відповідайте на нього.</p>
                <p>&copy; 2024 WebCraft Pro. Всі права захищені.</p>
            </div>
        </body>
        </html>
        """

        # Оновлюємо HTML частину зі стилями
        html_part = MIMEText(styled_content, "html", "utf-8")
        msg.attach(html_part)

        return msg

    async def send_email_async(self, to_email: str, subject: str, content: str,
                               from_name: str = "WebCraft Pro") -> bool:
        """Асинхронна відправка email."""
        try:
            if not settings.validate_email_config():
                logger.error("Email configuration is invalid")
                return False

            msg = self._create_message(to_email, subject, content, from_name)

            # Створюємо SMTP клієнт
            if self.use_ssl:
                smtp_client = aiosmtplib.SMTP(hostname=self.smtp_server, port=self.smtp_port, use_tls=False)
                await smtp_client.connect()
                await smtp_client.starttls()
            else:
                smtp_client = aiosmtplib.SMTP(hostname=self.smtp_server, port=self.smtp_port, use_tls=self.use_tls)
                await smtp_client.connect()

            # Авторизуємось
            await smtp_client.login(self.username, self.password)

            # Відправляємо повідомлення
            await smtp_client.send_message(msg)
            await smtp_client.quit()

            logger.info(f"Email sent successfully to {to_email}")

            # Логуємо відправку в БД
            await self._log_email_send(to_email, subject, content, "sent")

            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            await self._log_email_send(to_email, subject, content, "failed", str(e))
            return False

    def send_email_sync(self, to_email: str, subject: str, content: str,
                        from_name: str = "WebCraft Pro") -> bool:
        """Синхронна відправка email."""
        try:
            if not settings.validate_email_config():
                logger.error("Email configuration is invalid")
                return False

            msg = self._create_message(to_email, subject, content, from_name)

            # Створюємо SMTP з'єднання
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                if self.use_tls:
                    server.starttls()

            # Авторизуємось
            server.login(self.username, self.password)

            # Відправляємо повідомлення
            server.send_message(msg)
            server.quit()

            logger.info(f"Email sent successfully to {to_email}")

            # Логуємо відправку в БД (синхронно)
            self._log_email_send_sync(to_email, subject, content, "sent")

            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            self._log_email_send_sync(to_email, subject, content, "failed", str(e))
            return False

    async def _log_email_send(self, recipient: str, subject: str, content: str,
                              status: str, error_message: Optional[str] = None):
        """Асинхронне логування відправки email в БД."""
        try:
            db = get_db_session()

            email_log = models.EmailLog(
                recipient_email=recipient,
                subject=subject,
                content=content[:1000] if len(content) > 1000 else content,  # Обмежуємо довжину
                status=status,
                error_message=error_message,
                sent_at=datetime.utcnow() if status == "sent" else None
            )

            db.add(email_log)
            db.commit()
            db.close()

        except Exception as e:
            logger.error(f"Failed to log email send: {e}")

    def _log_email_send_sync(self, recipient: str, subject: str, content: str,
                             status: str, error_message: Optional[str] = None):
        """Синхронне логування відправки email в БД."""
        try:
            db = get_db_session()

            email_log = models.EmailLog(
                recipient_email=recipient,
                subject=subject,
                content=content[:1000] if len(content) > 1000 else content,
                status=status,
                error_message=error_message,
                sent_at=datetime.utcnow() if status == "sent" else None
            )

            db.add(email_log)
            db.commit()
            db.close()

        except Exception as e:
            logger.error(f"Failed to log email send: {e}")

    async def send_template_email(self, template_name: str, to_email: str,
                                  language: str = "uk", **template_vars) -> bool:
        """Відправляє email використовуючи шаблон."""
        if template_name not in self.templates:
            logger.error(f"Template not found: {template_name}")
            return False

        template = self.templates[template_name]
        subject, content = template.render(language, **template_vars)

        return await self.send_email_async(to_email, subject, content)

    # ============ СПЕЦІАЛІЗОВАНІ МЕТОДИ ============

    async def send_quote_application_notification(self, application: models.QuoteApplication) -> bool:
        """Відправляє сповіщення про нову заявку на прорахунок."""
        package_info = ""
        if application.package:
            package_info = f"<p><strong>Обраний пакет:</strong> {application.package.name}</p>"
        elif application.package_name:
            package_info = f"<p><strong>Обраний пакет:</strong> {application.package_name}</p>"

        template_vars = {
            "name": application.name,
            "email": application.email,
            "phone": application.phone or "Не вказано",
            "project_type": application.project_type,
            "budget": application.budget or "Не вказано",
            "description": application.description,
            "package_info": package_info,
            "created_at": application.created_at.strftime("%d.%m.%Y %H:%M")
        }

        # Відправляємо адміну
        success = await self.send_template_email(
            "quote_application",
            settings.ADMIN_EMAIL_NOTIFICATIONS,
            "uk",
            **template_vars
        )

        # Відправляємо підтвердження клієнту
        if success:
            client_vars = {
                "name": application.name,
                "project_type": application.project_type,
                "budget": application.budget or "Не вказано",
                "phone": application.phone or "Не вказано",
                "support_email": settings.SUPPORT_EMAIL,
                "support_phone": "+380123456789",  # Можна винести в налаштування
                "support_telegram": "@webcraftpro"  # Можна винести в налаштування
            }

            await self.send_template_email(
                "quote_confirmation",
                application.email,
                "uk",
                **client_vars
            )

        return success

    async def send_consultation_application_notification(self, application: models.ConsultationApplication) -> bool:
        """Відправляє сповіщення про нову заявку на консультацію."""
        template_vars = {
            "first_name": application.first_name,
            "last_name": application.last_name,
            "phone": application.phone,
            "telegram": application.telegram,
            "message": application.message or "Повідомлення не залишено",
            "created_at": application.created_at.strftime("%d.%m.%Y %H:%M")
        }

        # Відправляємо адміну
        success = await self.send_template_email(
            "consultation_application",
            settings.ADMIN_EMAIL_NOTIFICATIONS,
            "uk",
            **template_vars
        )

        # Відправляємо підтвердження клієнту (якщо є email)
        # Зазвичай в заявках на консультацію email не збирається

        return success

    async def send_review_moderation_notification(self, review: models.Review) -> bool:
        """Відправляє сповіщення про новий відгук на модерацію."""
        template_vars = {
            "author_name": review.user.name,
            "author_email": review.user.email,
            "company": review.company or "Не вказана",
            "rating": review.rating,
            "review_text": review.text,
            "created_at": review.created_at.strftime("%d.%m.%Y %H:%M"),
            "admin_url": "https://admin.webcraft.pro",  # Можна винести в налаштування
            "review_id": review.id
        }

        return await self.send_template_email(
            "review_moderation",
            settings.ADMIN_EMAIL_NOTIFICATIONS,
            "uk",
            **template_vars
        )

    async def send_password_reset_email(self, user_email: str, reset_token: str) -> bool:
        """Відправляє email для скидання пароля."""
        reset_url = f"https://webcraft.pro/reset-password?token={reset_token}"  # Можна винести в налаштування

        template_vars = {
            "reset_url": reset_url
        }

        return await self.send_template_email(
            "password_reset",
            user_email,
            "uk",
            **template_vars
        )

    async def send_bulk_email(self, recipients: List[str], template_name: str,
                              language: str = "uk", **template_vars) -> Dict[str, bool]:
        """Масова розсилка email."""
        results = {}

        for recipient in recipients:
            try:
                success = await self.send_template_email(
                    template_name, recipient, language, **template_vars
                )
                results[recipient] = success

                # Додаємо невелику затримку між повідомленнями
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Failed to send bulk email to {recipient}: {e}")
                results[recipient] = False

        return results

    async def test_email_connection(self) -> bool:
        """Тестує з'єднання з SMTP сервером."""
        try:
            if self.use_ssl:
                smtp_client = aiosmtplib.SMTP(hostname=self.smtp_server, port=self.smtp_port, use_tls=False)
                await smtp_client.connect()
                await smtp_client.starttls()
            else:
                smtp_client = aiosmtplib.SMTP(hostname=self.smtp_server, port=self.smtp_port, use_tls=self.use_tls)
                await smtp_client.connect()

            await smtp_client.login(self.username, self.password)
            await smtp_client.quit()

            logger.info("Email connection test successful")
            return True

        except Exception as e:
            logger.error(f"Email connection test failed: {e}")
            return False

    def get_email_stats(self) -> Dict[str, Any]:
        """Отримує статистику відправлених email."""
        try:
            db = get_db_session()

            total_emails = db.query(models.EmailLog).count()
            sent_emails = db.query(models.EmailLog).filter(models.EmailLog.status == "sent").count()
            failed_emails = db.query(models.EmailLog).filter(models.EmailLog.status == "failed").count()

            # Статистика за останні 24 години
            from datetime import timedelta
            yesterday = datetime.utcnow() - timedelta(days=1)

            recent_emails = db.query(models.EmailLog).filter(
                models.EmailLog.created_at >= yesterday
            ).count()

            db.close()

            return {
                "total_emails": total_emails,
                "sent_emails": sent_emails,
                "failed_emails": failed_emails,
                "success_rate": (sent_emails / total_emails * 100) if total_emails > 0 else 0,
                "recent_emails_24h": recent_emails
            }

        except Exception as e:
            logger.error(f"Failed to get email stats: {e}")
            return {}


# Глобальний екземпляр сервісу
email_service = EmailService()


# ============ BACKGROUND TASK ФУНКЦІЇ ============

async def send_quote_notification_task(application_id: int):
    """Background task для відправки сповіщення про заявку на прорахунок."""
    try:
        db = get_db_session()
        application = db.query(models.QuoteApplication).filter(
            models.QuoteApplication.id == application_id
        ).first()

        if application:
            await email_service.send_quote_application_notification(application)

        db.close()

    except Exception as e:
        logger.error(f"Failed to send quote notification task: {e}")


async def send_consultation_notification_task(application_id: int):
    """Background task для відправки сповіщення про заявку на консультацію."""
    try:
        db = get_db_session()
        application = db.query(models.ConsultationApplication).filter(
            models.ConsultationApplication.id == application_id
        ).first()

        if application:
            await email_service.send_consultation_application_notification(application)

        db.close()

    except Exception as e:
        logger.error(f"Failed to send consultation notification task: {e}")


async def send_review_notification_task(review_id: int):
    """Background task для відправки сповіщення про новий відгук."""
    try:
        db = get_db_session()
        review = db.query(models.Review).options(
            models.joinedload(models.Review.user)
        ).filter(models.Review.id == review_id).first()

        if review:
            await email_service.send_review_moderation_notification(review)

        db.close()

    except Exception as e:
        logger.error(f"Failed to send review notification task: {e}")