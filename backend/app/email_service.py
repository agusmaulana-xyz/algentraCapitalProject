from email.message import EmailMessage
import smtplib
import ssl

from .config import Settings


def send_verification_code(settings: Settings, recipient: str, code: str) -> None:
    if not settings.email_configured:
        raise RuntimeError("SMTP email belum dikonfigurasi")

    message = EmailMessage()
    message["Subject"] = "Kode verifikasi Algentra Capital"
    message["From"] = settings.email_from
    message["To"] = recipient
    message.set_content(
        f"Kode verifikasi pendaftaran Algentra Capital: {code}\n\n"
        "Kode berlaku selama 10 menit dan hanya dapat digunakan satu kali. "
        "Jika Anda tidak meminta kode ini, abaikan email ini."
    )

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=10) as smtp:
        if settings.email_smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(settings.email_smtp_username, settings.email_smtp_password.get_secret_value())
        smtp.send_message(message)
