import smtplib
import aiosmtplib
import re
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
            ),

            # НОВЫЙ ШАБЛОН: Уведомление о смене пароля
            "password_changed": EmailTemplate(
                name="password_changed",
                subject_uk="Пароль змінено - WebCraft Pro",
                subject_en="Password Changed - WebCraft Pro",
                content_uk="""
                <h2>Пароль успішно змінено</h2>
                <p>Вітаю, {user_name}!</p>

                <p>Ваш пароль був успішно змінений {changed_at}.</p>

                <div style="background: #d4edda; padding: 15px; border-left: 4px solid #28a745; margin: 20px 0;">
                    <strong>Деталі:</strong><br>
                    IP адреса: {ip_address}<br>
                    Браузер: {user_agent}<br>
                    Дата та час: {changed_at}
                </div>

                <p>Якщо ви не змінювали пароль, негайно зв'яжіться з нами:</p>
                <ul>
                    <li>Email: {support_email}</li>
                    <li>Телефон: {support_phone}</li>
                </ul>

                <p>З міркувань безпеки рекомендуємо:</p>
                <ul>
                    <li>Використовувати складні паролі</li>
                    <li>Не передавати пароль іншим особам</li>
                    <li>Регулярно оновлювати пароль</li>
                </ul>

                <p>З повагою,<br>Команда WebCraft Pro</p>
                """,
                content_en="""
                <h2>Password Successfully Changed</h2>
                <p>Hello {user_name}!</p>

                <p>Your password was successfully changed on {changed_at}.</p>

                <div style="background: #d4edda; padding: 15px; border-left: 4px solid #28a745; margin: 20px 0;">
                    <strong>Details:</strong><br>
                    IP Address: {ip_address}<br>
                    Browser: {user_agent}<br>
                    Date and Time: {changed_at}
                </div>

                <p>If you did not change your password, please contact us immediately:</p>
                <ul>
                    <li>Email: {support_email}</li>
                    <li>Phone: {support_phone}</li>
                </ul>

                <p>For security reasons, we recommend:</p>
                <ul>
                    <li>Using strong passwords</li>
                    <li>Not sharing your password with others</li>
                    <li>Regularly updating your password</li>
                </ul>

                <p>Best regards,<br>WebCraft Pro Team</p>
                """,
                variables=["user_name", "changed_at", "ip_address", "user_agent", "support_email", "support_phone"]
            ),

            # НОВЫЙ ШАБЛОН: Уведомление о добавлении в команду
            "team_member_added": EmailTemplate(
                name="team_member_added",
                subject_uk="Вас додано до команди WebCraft Pro",
                subject_en="You've been added to WebCraft Pro team",
                content_uk="""
                <h2>Ласкаво просимо до команди WebCraft Pro!</h2>
                <p>Вітаю, {member_name}!</p>

                <p>Ми раді повідомити, що вас додано до нашої команди на посаду <strong>{role_uk}</strong>.</p>

                <h3>Ваша інформація в команді:</h3>
                <ul>
                    <li><strong>Ім'я:</strong> {member_name}</li>
                    <li><strong>Посада:</strong> {role_uk}</li>
                    <li><strong>Навички:</strong> {skills}</li>
                </ul>

                <p>Ваш профіль тепер відображається на нашому сайті в розділі "Про нас".</p>

                <p>Якщо у вас є питання або потрібно внести зміни в профіль, зв'яжіться з нами:</p>
                <ul>
                    <li>Email: {admin_email}</li>
                    <li>Телефон: {admin_phone}</li>
                </ul>

                <p>Дякуємо, що є частиною нашої команди!</p>

                <p>З повагою,<br>Команда WebCraft Pro</p>
                """,
                content_en="""
                <h2>Welcome to the WebCraft Pro team!</h2>
                <p>Hello {member_name}!</p>

                <p>We are pleased to inform you that you have been added to our team as <strong>{role_en}</strong>.</p>

                <h3>Your team information:</h3>
                <ul>
                    <li><strong>Name:</strong> {member_name}</li>
                    <li><strong>Position:</strong> {role_en}</li>
                    <li><strong>Skills:</strong> {skills}</li>
                </ul>

                <p>Your profile is now displayed on our website in the "About Us" section.</p>

                <p>If you have any questions or need to make changes to your profile, please contact us:</p>
                <ul>
                    <li>Email: {admin_email}</li>
                    <li>Phone: {admin_phone}</li>
                </ul>

                <p>Thank you for being part of our team!</p>

                <p>Best regards,<br>WebCraft Pro Team</p>
                """,
                variables=["member_name", "role_uk", "role_en", "skills", "admin_email", "admin_phone"]
            ),

            # НОВЫЙ ШАБЛОН: Уведомление администратору о новом члене команды
            "team_member_admin_notification": EmailTemplate(
                name="team_member_admin_notification",
                subject_uk="Новий член команди доданий",
                subject_en="New Team Member Added",
                content_uk="""
                <h2>Новий член команди</h2>
                <p>До команди WebCraft Pro додано нового учасника:</p>

                <h3>Інформація про нового члена:</h3>
                <ul>
                    <li><strong>Ім'я:</strong> {member_name}</li>
                    <li><strong>Посада (UK):</strong> {role_uk}</li>
                    <li><strong>Посада (EN):</strong> {role_en}</li>
                    <li><strong>Навички:</strong> {skills}</li>
                    <li><strong>Ініціали:</strong> {initials}</li>
                    <li><strong>Позиція в команді:</strong> {order_index}</li>
                </ul>

                <p><strong>Додано:</strong> {created_at}</p>
                <p><strong>Статус:</strong> {status}</p>

                <p><a href="{admin_url}/team/{member_id}">Переглянути в адмін-панелі</a></p>
                """,
                content_en="""
                <h2>New Team Member</h2>
                <p>A new member has been added to the WebCraft Pro team:</p>

                <h3>New Member Information:</h3>
                <ul>
                    <li><strong>Name:</strong> {member_name}</li>
                    <li><strong>Role (UK):</strong> {role_uk}</li>
                    <li><strong>Role (EN):</strong> {role_en}</li>
                    <li><strong>Skills:</strong> {skills}</li>
                    <li><strong>Initials:</strong> {initials}</li>
                    <li><strong>Team Position:</strong> {order_index}</li>
                </ul>

                <p><strong>Added:</strong> {created_at}</p>
                <p><strong>Status:</strong> {status}</p>

                <p><a href="{admin_url}/team/{member_id}">View in Admin Panel</a></p>
                """,
                variables=["member_name", "role_uk", "role_en", "skills", "initials", "order_index",
                           "created_at", "status", "admin_url", "member_id"]
            ),

            # НОВЫЙ ШАБЛОН: Безопасность - подозрительная активность
            "security_alert": EmailTemplate(
                name="security_alert",
                subject_uk="Сповіщення безпеки - WebCraft Pro",
                subject_en="Security Alert - WebCraft Pro",
                content_uk="""
                <h2>🔒 Сповіщення безпеки</h2>
                <p>Виявлено підозрілу активність в вашому акаунті:</p>

                <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0;">
                    <strong>Деталі активності:</strong><br>
                    Тип: {activity_type}<br>
                    IP адреса: {ip_address}<br>
                    Браузер: {user_agent}<br>
                    Дата та час: {activity_time}<br>
                    Місцезнаходження: {location}
                </div>

                <p>Якщо це були ви, проігноруйте це повідомлення.</p>

                <p>Якщо ви не виконували цю дію:</p>
                <ol>
                    <li>Негайно змініть свій пароль</li>
                    <li>Перевірте налаштування акаунту</li>
                    <li>Зв'яжіться з нами для розслідування</li>
                </ol>

                <p>Зв'язатися з підтримкою:</p>
                <ul>
                    <li>Email: {support_email}</li>
                    <li>Телефон: {support_phone}</li>
                </ul>

                <p>З повагою,<br>Команда безпеки WebCraft Pro</p>
                """,
                content_en="""
                <h2>🔒 Security Alert</h2>
                <p>Suspicious activity has been detected in your account:</p>

                <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0;">
                    <strong>Activity Details:</strong><br>
                    Type: {activity_type}<br>
                    IP Address: {ip_address}<br>
                    Browser: {user_agent}<br>
                    Date and Time: {activity_time}<br>
                    Location: {location}
                </div>

                <p>If this was you, please ignore this message.</p>

                <p>If you did not perform this action:</p>
                <ol>
                    <li>Change your password immediately</li>
                    <li>Review your account settings</li>
                    <li>Contact us for investigation</li>
                </ol>

                <p>Contact Support:</p>
                <ul>
                    <li>Email: {support_email}</li>
                    <li>Phone: {support_phone}</li>
                </ul>

                <p>Best regards,<br>WebCraft Pro Security Team</p>
                """,
                variables=["activity_type", "ip_address", "user_agent", "activity_time", "location",
                           "support_email", "support_phone"]
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
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; 
                    line-height: 1.6; 
                    color: #333; 
                    max-width: 600px; 
                    margin: 0 auto; 
                    padding: 20px; 
                    background-color: #f8f9fa;
                }}
                .container {{
                    background-color: #ffffff;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    padding: 30px;
                    margin: 20px 0;
                }}
                h1, h2, h3 {{ 
                    color: #007bff; 
                    margin-top: 0;
                }}
                h2 {{ 
                    border-bottom: 2px solid #007bff; 
                    padding-bottom: 10px; 
                }}
                .footer {{ 
                    margin-top: 40px; 
                    padding-top: 20px; 
                    border-top: 1px solid #eee; 
                    font-size: 12px; 
                    color: #666; 
                    text-align: center;
                }}
                .button {{ 
                    display: inline-block; 
                    background: linear-gradient(135deg, #007bff 0%, #0056b3 100%); 
                    color: white !important; 
                    padding: 12px 24px; 
                    text-decoration: none; 
                    border-radius: 6px; 
                    font-weight: 600;
                    box-shadow: 0 2px 4px rgba(0,123,255,0.3);
                    transition: all 0.3s ease;
                }}
                .button:hover {{
                    background: linear-gradient(135deg, #0056b3 0%, #004085 100%);
                    transform: translateY(-1px);
                    box-shadow: 0 4px 8px rgba(0,123,255,0.4);
                }}
                .highlight {{ 
                    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); 
                    padding: 20px; 
                    border-left: 4px solid #007bff; 
                    margin: 15px 0; 
                    border-radius: 4px;
                }}
                .alert {{
                    padding: 15px;
                    border-radius: 6px;
                    margin: 15px 0;
                }}
                .alert-success {{
                    background-color: #d4edda;
                    border-left: 4px solid #28a745;
                    color: #155724;
                }}
                .alert-warning {{
                    background-color: #fff3cd;
                    border-left: 4px solid #ffc107;
                    color: #856404;
                }}
                .alert-info {{
                    background-color: #d1ecf1;
                    border-left: 4px solid #17a2b8;
                    color: #0c5460;
                }}
                ul, ol {{
                    padding-left: 20px;
                }}
                li {{
                    margin: 8px 0;
                }}
                a {{
                    color: #007bff;
                    text-decoration: none;
                }}
                a:hover {{
                    text-decoration: underline;
                }}
                .social-links {{
                    text-align: center;
                    margin: 20px 0;
                }}
                .social-links a {{
                    display: inline-block;
                    margin: 0 10px;
                    padding: 8px 16px;
                    background: #f8f9fa;
                    border-radius: 4px;
                    color: #007bff;
                    text-decoration: none;
                    font-size: 14px;
                }}
                @media (max-width: 600px) {{
                    body {{ padding: 10px; }}
                    .container {{ padding: 20px; }}
                    .button {{ display: block; text-align: center; margin: 10px 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                {content}
                <div class="footer">
                    <p>Цей лист надіслано автоматично. Будь ласка, не відповідайте на нього.</p>
                    <div class="social-links">
                        <a href="https://webcraft.pro">Веб-сайт</a>
                        <a href="mailto:{settings.SUPPORT_EMAIL}">Підтримка</a>
                        <a href="https://t.me/webcraftpro">Telegram</a>
                    </div>
                    <p>&copy; 2025 WebCraft Pro. Всі права захищені.</p>
                </div>
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
        elif hasattr(application, 'package_name') and application.package_name:
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

        return success

    async def send_review_moderation_notification(self, review: models.Review) -> bool:
        """Відправляє сповіщення про новий відгук на модерацію."""
        # Визначаємо автора відгуку
        author_name = "Анонім"
        author_email = "anonymous@example.com"

        if review.user:
            author_name = review.user.name
            author_email = review.user.email
        elif review.author_name:
            author_name = review.author_name
            if review.author_email:
                author_email = review.author_email

        template_vars = {
            "author_name": author_name,
            "author_email": author_email,
            "company": review.company or "Не вказана",
            "rating": review.rating,
            "review_text": review.text_uk or review.text_en or "Текст відгуку відсутній",
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

    # НОВЫЕ МЕТОДЫ для команды и безопасности

    async def send_password_changed_notification(self, user: models.User, ip_address: str = "Unknown",
                                                 user_agent: str = "Unknown") -> bool:
        """Відправляє сповіщення про зміну пароля."""
        template_vars = {
            "user_name": user.name,
            "changed_at": datetime.utcnow().strftime("%d.%m.%Y %H:%M"),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "support_email": settings.SUPPORT_EMAIL,
            "support_phone": "+380123456789"  # Можна винести в налаштування
        }

        return await self.send_template_email(
            "password_changed",
            user.email,
            "uk",
            **template_vars
        )

    async def send_team_member_added_notification(self, member: models.TeamMember,
                                                  member_email: Optional[str] = None) -> bool:
        """Відправляє сповіщення новому члену команди."""
        if not member_email:
            logger.warning(f"No email provided for team member {member.name}")
            return False

        template_vars = {
            "member_name": member.name,
            "role_uk": member.role_uk,
            "role_en": member.role_en,
            "skills": member.skills or "Не вказано",
            "admin_email": settings.ADMIN_EMAIL_NOTIFICATIONS,
            "admin_phone": "+380123456789"  # Можна винести в налаштування
        }

        return await self.send_template_email(
            "team_member_added",
            member_email,
            "uk",
            **template_vars
        )

    async def send_team_member_admin_notification(self, member: models.TeamMember) -> bool:
        """Відправляє сповіщення адміну про нового члена команди."""
        template_vars = {
            "member_name": member.name,
            "role_uk": member.role_uk,
            "role_en": member.role_en,
            "skills": member.skills or "Не вказано",
            "initials": member.initials,
            "order_index": member.order_index,
            "created_at": member.created_at.strftime("%d.%m.%Y %H:%M"),
            "status": "Активний" if member.is_active else "Неактивний",
            "admin_url": "https://admin.webcraft.pro",  # Можна винести в налаштування
            "member_id": member.id
        }

        return await self.send_template_email(
            "team_member_admin_notification",
            settings.ADMIN_EMAIL_NOTIFICATIONS,
            "uk",
            **template_vars
        )

    async def send_security_alert(self, user_email: str, activity_type: str,
                                  ip_address: str = "Unknown", user_agent: str = "Unknown",
                                  location: str = "Unknown") -> bool:
        """Відправляє сповіщення про підозрілу активність."""
        template_vars = {
            "activity_type": activity_type,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "activity_time": datetime.utcnow().strftime("%d.%m.%Y %H:%M"),
            "location": location,
            "support_email": settings.SUPPORT_EMAIL,
            "support_phone": "+380123456789"  # Можна винести в налаштування
        }

        return await self.send_template_email(
            "security_alert",
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

            # Статистика за типами шаблонів
            template_stats = {}
            for template_name in self.templates.keys():
                count = db.query(models.EmailLog).filter(
                    models.EmailLog.template_name == template_name,
                    models.EmailLog.status == "sent"
                ).count()
                template_stats[template_name] = count

            db.close()

            return {
                "total_emails": total_emails,
                "sent_emails": sent_emails,
                "failed_emails": failed_emails,
                "success_rate": (sent_emails / total_emails * 100) if total_emails > 0 else 0,
                "recent_emails_24h": recent_emails,
                "template_stats": template_stats
            }

        except Exception as e:
            logger.error(f"Failed to get email stats: {e}")
            return {}

    def get_available_templates(self) -> Dict[str, Dict[str, Any]]:
        """Повертає список доступних шаблонів email."""
        templates_info = {}

        for name, template in self.templates.items():
            templates_info[name] = {
                "name": template.name,
                "subject_uk": template.subject_uk,
                "subject_en": template.subject_en,
                "variables": template.variables,
                "description": self._get_template_description(name)
            }

        return templates_info

    def _get_template_description(self, template_name: str) -> str:
        """Повертає опис шаблону."""
        descriptions = {
            "quote_application": "Сповіщення про нову заявку на прорахунок проекту",
            "consultation_application": "Сповіщення про нову заявку на консультацію",
            "quote_confirmation": "Підтвердження заявки клієнту",
            "consultation_confirmation": "Підтвердження консультації клієнту",
            "review_moderation": "Сповіщення про новий відгук на модерацію",
            "password_reset": "Відновлення пароля",
            "password_changed": "Сповіщення про зміну пароля",
            "team_member_added": "Сповіщення новому члену команди",
            "team_member_admin_notification": "Сповіщення адміну про нового члена команди",
            "security_alert": "Сповіщення безпеки про підозрілу активність"
        }

        return descriptions.get(template_name, "Опис недоступний")


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
        from sqlalchemy.orm import joinedload

        review = db.query(models.Review).options(
            joinedload(models.Review.user)
        ).filter(models.Review.id == review_id).first()

        if review:
            await email_service.send_review_moderation_notification(review)

        db.close()

    except Exception as e:
        logger.error(f"Failed to send review notification task: {e}")


async def send_team_member_notification_task(member_id: int, member_email: Optional[str] = None):
    """Background task для відправки сповіщення про нового члена команди."""
    try:
        db = get_db_session()
        member = db.query(models.TeamMember).filter(
            models.TeamMember.id == member_id
        ).first()

        if member:
            # Відправляємо сповіщення адміну
            await email_service.send_team_member_admin_notification(member)

            # Відправляємо сповіщення члену команди якщо є email
            if member_email:
                await email_service.send_team_member_added_notification(member, member_email)

        db.close()

    except Exception as e:
        logger.error(f"Failed to send team member notification task: {e}")


async def send_password_changed_notification_task(user_id: int, ip_address: str = "Unknown",
                                                  user_agent: str = "Unknown"):
    """Background task для відправки сповіщення про зміну пароля."""
    try:
        db = get_db_session()
        user = db.query(models.User).filter(
            models.User.id == user_id
        ).first()

        if user:
            await email_service.send_password_changed_notification(user, ip_address, user_agent)

        db.close()

    except Exception as e:
        logger.error(f"Failed to send password changed notification task: {e}")


async def send_security_alert_task(user_email: str, activity_type: str,
                                   ip_address: str = "Unknown", user_agent: str = "Unknown",
                                   location: str = "Unknown"):
    """Background task для відправки сповіщення безпеки."""
    try:
        await email_service.send_security_alert(
            user_email, activity_type, ip_address, user_agent, location
        )
    except Exception as e:
        logger.error(f"Failed to send security alert task: {e}")


# ============ ШАБЛОННІ ФУНКЦІЇ ДЛЯ СПРОЩЕННЯ ============

async def send_welcome_email(user_email: str, user_name: str) -> bool:
    """Швидка функція для відправки привітального email."""
    content = f"""
    <h2>Ласкаво просимо до WebCraft Pro!</h2>
    <p>Вітаю, {user_name}!</p>
    <p>Дякуємо за реєстрацію на нашому сайті. Тепер ви можете залишати відгуки та слідкувати за нашими проектами.</p>
    <p>З повагою,<br>Команда WebCraft Pro</p>
    """

    return await email_service.send_email_async(
        user_email,
        "Ласкаво просимо до WebCraft Pro!",
        content
    )


async def send_test_email(to_email: str) -> bool:
    """Відправляє тестовий email для перевірки налаштувань."""
    content = """
    <h2>Тестове повідомлення</h2>
    <p>Це тестове повідомлення для перевірки налаштувань email сервісу.</p>
    <p>Якщо ви отримали це повідомлення, значить налаштування працюють коректно.</p>
    <p>Дата відправки: """ + datetime.now().strftime("%d.%m.%Y %H:%M:%S") + """</p>
    """

    return await email_service.send_email_async(
        to_email,
        "Тестове повідомлення - WebCraft Pro",
        content
    )


# ============ EMAIL VALIDATOR ============

def validate_email_templates() -> Dict[str, Any]:
    """Валідує всі email шаблони."""
    validation_results = {}

    for template_name, template in email_service.templates.items():
        errors = []

        # Перевіряємо наявність обов'язкових полів
        if not template.subject_uk or len(template.subject_uk.strip()) < 5:
            errors.append("Subject Ukrainian is too short or empty")

        if not template.subject_en or len(template.subject_en.strip()) < 5:
            errors.append("Subject English is too short or empty")

        if not template.content_uk or len(template.content_uk.strip()) < 20:
            errors.append("Content Ukrainian is too short or empty")

        if not template.content_en or len(template.content_en.strip()) < 20:
            errors.append("Content English is too short or empty")

        # Перевіряємо змінні в контенті
        content_vars_uk = set(re.findall(r'\{(\w+)\}', template.content_uk))
        content_vars_en = set(re.findall(r'\{(\w+)\}', template.content_en))
        declared_vars = set(template.variables)

        missing_vars_uk = content_vars_uk - declared_vars
        missing_vars_en = content_vars_en - declared_vars

        if missing_vars_uk:
            errors.append(f"Ukrainian content has undeclared variables: {missing_vars_uk}")
        if missing_vars_en:
            errors.append(f"English content has undeclared variables: {missing_vars_en}")

        validation_results[template_name] = {
            "valid": len(errors) == 0,
            "errors": errors,
            "variables_count": len(template.variables),
            "content_length_uk": len(template.content_uk),
            "content_length_en": len(template.content_en)
        }

    return validation_results