"""Transactional account email over standard SMTP."""

from __future__ import annotations

import html
import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

import config


class EmailDeliveryError(RuntimeError):
    pass


def configured() -> bool:
    if config.RESEND_API_KEY:
        return bool(config.SMTP_FROM and config.PUBLIC_APP_URL)
    has_auth = not config.SMTP_USERNAME or bool(config.SMTP_PASSWORD)
    return bool(config.SMTP_HOST and config.SMTP_FROM and config.PUBLIC_APP_URL and has_auth)


def _send_resend(recipient: str, subject: str, text: str, html_body: str) -> None:
    payload = json.dumps({
        "from": config.SMTP_FROM,
        "to": [recipient],
        "subject": subject,
        "text": text,
        "html": html_body,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "ResearchAgentLab/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status < 200 or response.status >= 300:
                raise EmailDeliveryError(
                    f"Resend API rejected the message (HTTP {response.status})."
                )
    except urllib.error.HTTPError as exc:
        raise EmailDeliveryError(
            f"Resend API rejected the message (HTTP {exc.code})."
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise EmailDeliveryError(
            f"Resend API could not be reached ({type(exc).__name__})."
        ) from exc


def _send_smtp(recipient: str, subject: str, text: str, html_body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.SMTP_FROM
    message["To"] = recipient
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.ehlo()
            if config.SMTP_STARTTLS:
                smtp.starttls()
                smtp.ehlo()
            if config.SMTP_USERNAME:
                smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError(
            f"SMTP delivery failed ({type(exc).__name__})."
        ) from exc


def _send(recipient: str, subject: str, text: str, html_body: str) -> None:
    if not configured():
        raise EmailDeliveryError("Account email is not configured on this server.")
    if config.RESEND_API_KEY:
        _send_resend(recipient, subject, text, html_body)
        return
    _send_smtp(recipient, subject, text, html_body)


def send_verification(recipient: str, token: str) -> None:
    link = f"{config.PUBLIC_APP_URL}/verify-email#token={token}"
    safe_link = html.escape(link, quote=True)
    _send(
        recipient,
        "Verify your ResearchAgentLab email",
        f"Verify your email by opening this link within 24 hours:\n\n{link}\n\n"
        "If you did not create this account, ignore this message.",
        "<p>Verify your email to activate your ResearchAgentLab account.</p>"
        f'<p><a href="{safe_link}">Verify email</a></p>'
        "<p>This link expires in 24 hours. If you did not create this account, "
        "ignore this message.</p>",
    )


def send_password_reset(recipient: str, token: str) -> None:
    link = f"{config.PUBLIC_APP_URL}/reset-password#token={token}"
    safe_link = html.escape(link, quote=True)
    _send(
        recipient,
        "Reset your ResearchAgentLab password",
        f"Reset your password by opening this link within 30 minutes:\n\n{link}\n\n"
        "If you did not request a reset, ignore this message.",
        "<p>A password reset was requested for your ResearchAgentLab account.</p>"
        f'<p><a href="{safe_link}">Reset password</a></p>'
        "<p>This link expires in 30 minutes and can be used once. If you did not "
        "request it, ignore this message.</p>",
    )
