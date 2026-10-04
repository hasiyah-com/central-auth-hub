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


def test_transient_disconnect_retries_once_and_succeeds(monkeypatch):
    attempts = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            attempts.append(1)
            self.should_fail = len(attempts) == 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, **kwargs):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            if self.should_fail:
                raise smtplib.SMTPServerDisconnected("connection closed")

    monkeypatch.setattr(email_service.settings, "smtp_user", "sender@example.com")
    monkeypatch.setattr(email_service.settings, "smtp_password", "configured")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_port", 587)
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    assert email_service._send_html_email("user@example.com", "subject", "html", "text")
    assert len(attempts) == 2


def test_permanent_data_error_is_not_retried(monkeypatch):
    attempts = []

    class RejectingSMTP:
        def __init__(self, *args, **kwargs):
            attempts.append(1)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, **kwargs):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            raise smtplib.SMTPDataError(554, b"message rejected")

    monkeypatch.setattr(email_service.settings, "smtp_user", "sender@example.com")
    monkeypatch.setattr(email_service.settings, "smtp_password", "configured")
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_port", 587)
    monkeypatch.setattr(email_service.smtplib, "SMTP", RejectingSMTP)

    with pytest.raises(EmailDeliveryError) as caught:
        email_service._send_html_email(
            "user@example.com", "subject", "html", "text", raise_on_error=True
        )

    assert caught.value.code == "smtp_message_rejected"
    assert caught.value.smtp_code == 554
    assert len(attempts) == 1
