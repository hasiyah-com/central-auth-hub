import smtplib

import pytest

from app.services import email_service
from app.services.email_service import EmailDeliveryError


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            smtplib.SMTPAuthenticationError(535, b"bad credentials"),
            "smtp_authentication_failed",
        ),
        (
            smtplib.SMTPRecipientsRefused({"user@example.com": (550, b"unknown")}),
            "recipient_rejected",
        ),
        (
            smtplib.SMTPSenderRefused(550, b"rejected", "sender@example.com"),
            "sender_rejected",
        ),
        (TimeoutError("timed out"), "smtp_connection_failed"),
        (smtplib.SMTPException("protocol"), "smtp_protocol_error"),
        (ValueError("unexpected"), "email_delivery_failed"),
    ],
)
def test_delivery_error_code_is_safe_and_specific(exc, expected):
    assert email_service._delivery_error_code(exc) == expected


def test_raise_on_error_reports_missing_configuration(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_user", "")
    monkeypatch.setattr(email_service.settings, "smtp_password", "")

    with pytest.raises(EmailDeliveryError) as caught:
        email_service._send_html_email(
            "user@example.com",
            "subject",
            "<p>body</p>",
            "body",
            raise_on_error=True,
        )

    assert caught.value.code == "smtp_not_configured"
