import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from fastapi import HTTPException
from backend.core.config import settings

log = logging.getLogger(__name__)


async def _send_email(recipient, subject, body):
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD or not settings.SMTP_FROM_EMAIL:
        raise HTTPException(503, "Отправка писем пока не настроена. Попробуйте позже.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(body)

    def send():
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT,
                              timeout=settings.SMTP_TIMEOUT_SECONDS, context=ssl.create_default_context()) as smtp:
            password = settings.SMTP_PASSWORD.get_secret_value()
            if settings.SMTP_HOST == "smtp.gmail.com":
                password = password.replace(" ", "")
            smtp.login(settings.SMTP_USERNAME, password)
            smtp.send_message(message)

    try:
        await asyncio.wait_for(asyncio.to_thread(send), settings.SMTP_TIMEOUT_SECONDS + 5)
    except (OSError, smtplib.SMTPException, asyncio.TimeoutError):
        log.warning("Email delivery failed")
        raise HTTPException(503, "Не удалось отправить письмо. Попробуйте позже.") from None


async def send_verification_email(recipient, code):
    await _send_email(recipient, "Amergination — подтверждение почты",
                      f"Ваш код подтверждения: {code}\n\nКод действует 2 минуты. Не сообщайте его другим людям.\nЕсли вы не запрашивали код, просто проигнорируйте письмо.")


async def send_password_reset_email(recipient, code):
    await _send_email(recipient, "Amergination — восстановление пароля",
                      f"Код восстановления пароля: {code}\n\nКод действует 2 минуты. Не сообщайте его другим людям.\nЕсли вы не запрашивали восстановление, проигнорируйте письмо: ваш пароль не изменится.")
