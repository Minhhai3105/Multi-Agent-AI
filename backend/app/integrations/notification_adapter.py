"""Notification Adapter: persists in-app notifications and optionally sends e-mail (FR6.3).

External delivery is best effort: an SMTP failure never breaks the business transaction.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Notification
from app.repositories.repos import NotificationRepository, UserRepository

log = logging.getLogger(__name__)


class NotificationAdapter:
    def __init__(self, db: Session):
        self.repo = NotificationRepository(db)
        self.users = UserRepository(db)
        self.settings = get_settings()

    def notify(self, user_id: int | None, title: str, message: str, link: str | None = None) -> None:
        if not user_id:
            return
        self.repo.add(Notification(user_id=user_id, title=title, message=message, link=link))
        if self.settings.smtp_host:
            user = self.users.get(user_id)
            if user:
                self._send_email(user.email, title, message)

    def _send_email(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.settings.smtp_sender or self.settings.smtp_user or "noreply@localhost"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if self.settings.smtp_user:
                    smtp.login(self.settings.smtp_user, self.settings.smtp_password or "")
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            log.warning("E-mail notification failed: %s", type(exc).__name__)
