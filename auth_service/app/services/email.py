"""Transactional email service via SendGrid."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)


class EmailService:
    async def _send(self, *, to: str, subject: str, html: str) -> None:
        if not settings.SENDGRID_API_KEY:
            log.warning("email_skipped_no_key", to=to, subject=subject)
            return
        try:
            import sendgrid
            from sendgrid.helpers.mail import Content, Email, Mail, To

            sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
            mail = Mail(
                from_email=Email(settings.EMAIL_FROM, settings.EMAIL_FROM_NAME),
                to_emails=To(to),
                subject=subject,
                html_content=Content("text/html", html),
            )
            sg.client.mail.send.post(request_body=mail.get())
        except Exception as exc:
            log.error("email_send_failed", to=to, subject=subject, error=str(exc))

    async def send_verification(self, *, email: str, token: str) -> None:
        link = f"https://sg-trading.local/verify-email?token={token}"
        await self._send(
            to=email,
            subject="Verify your SG Trading email",
            html=f"""
            <h2>Email Verification</h2>
            <p>Click the link below to verify your email. Expires in {settings.EMAIL_VERIFICATION_EXPIRE_HOURS} hours.</p>
            <a href="{link}">{link}</a>
            """,
        )
        log.info("verification_email_sent", email=email)

    async def send_password_reset(self, *, email: str, token: str) -> None:
        link = f"https://sg-trading.local/reset-password?token={token}"
        await self._send(
            to=email,
            subject="Reset your SG Trading password",
            html=f"""
            <h2>Password Reset</h2>
            <p>Click below to reset your password. Expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes.</p>
            <a href="{link}">{link}</a>
            <p>If you didn't request this, ignore this email.</p>
            """,
        )
        log.info("password_reset_email_sent", email=email)

    async def send_new_device_alert(self, *, email: str, device: str, ip: str) -> None:
        await self._send(
            to=email,
            subject="New device login — SG Trading",
            html=f"""
            <h2>New Device Login</h2>
            <p>A login was detected from <strong>{device}</strong> at IP <strong>{ip}</strong>.</p>
            <p>If this wasn't you, change your password immediately.</p>
            """,
        )
