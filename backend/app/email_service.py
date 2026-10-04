from email.message import EmailMessage
from html import escape
import smtplib
import ssl
from urllib.parse import urlsplit

from .config import Settings


SOCIAL_CONTACTS = (
    ("Instagram", "contact_instagram", ("instagram.com",)),
    ("Telegram", "contact_telegram", ("t.me", "telegram.me")),
    ("Telegram Admin", "contact_telegram_admin", ("t.me", "telegram.me")),
    ("Facebook", "contact_facebook", ("facebook.com", "fb.com")),
    ("LinkedIn", "contact_linkedin", ("linkedin.com",)),
    ("X", "contact_x", ("x.com", "twitter.com")),
    ("YouTube", "contact_youtube", ("youtube.com", "youtu.be")),
    ("TikTok", "contact_tiktok", ("tiktok.com",)),
    ("Website", "contact_website", ("algentracapital.my.id",)),
)


def _configured_social_links(settings: Settings) -> list[tuple[str, str]]:
    links = []
    for label, setting_name, allowed_hosts in SOCIAL_CONTACTS:
        url = (getattr(settings, setting_name) or "").strip()
        try:
            parsed = urlsplit(url)
            hostname = (parsed.hostname or "").casefold()
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts)
        ):
            links.append((label, url))
    return links


def send_verification_code(settings: Settings, recipient: str, code: str, purpose: str = "registration") -> None:
    if not settings.email_configured:
        raise RuntimeError("SMTP email belum dikonfigurasi")

    message = EmailMessage()
    is_password_reset = purpose == "password_reset"
    action = "reset kata sandi" if is_password_reset else "verifikasi email"
    heading = "Atur ulang kata sandi" if is_password_reset else "Verifikasi email Anda"
    message["Subject"] = "Kode reset kata sandi Algentra Capital" if is_password_reset else "Kode verifikasi Algentra Capital"
    message["From"] = settings.email_from
    message["To"] = recipient

    social_links = _configured_social_links(settings)
    text_socials = "\n".join(f"{label}: {url}" for label, url in social_links)
    message.set_content(
        f"ALGENTRA CAPITAL | KEAMANAN AKUN\n\n"
        f"{heading}\n"
        f"Gunakan kode berikut untuk {action} akun Algentra Capital:\n\n"
        f"{code}\n\n"
        "Kode berlaku selama 10 menit dan hanya dapat digunakan satu kali.\n"
        "Jangan bagikan kode ini kepada siapa pun. Tim Algentra tidak akan meminta OTP Anda.\n\n"
        "Jika Anda tidak meminta kode ini, abaikan email ini; akun Anda tetap aman.\n"
        + (f"\nIkuti Algentra Capital:\n{text_socials}\n" if text_socials else "")
        + "\nAlgentra Capital | Trading memiliki risiko."
    )

    safe_code = escape(code)
    safe_heading = escape(heading)
    safe_action = escape(action)
    social_html = ""
    if social_links:
        social_items = "".join(
            '<a href="{}" style="display:inline-block;margin:4px 5px;padding:7px 11px;'
            'border:1px solid #34463f;border-radius:999px;color:#c4d8ca;text-decoration:none;'
            'font-size:12px;line-height:1.2">{}</a>'.format(escape(url, quote=True), escape(label))
            for label, url in social_links
        )
        social_html = (
            '<tr><td style="padding:25px 30px 4px;text-align:center">'
            '<p style="margin:0 0 8px;color:#9aa9a1;font-size:10px;font-weight:700;'
            'letter-spacing:1.5px;text-transform:uppercase">Ikuti Algentra Capital</p>'
            f'<div>{social_items}</div></td></tr>'
        )

    html_body = f"""<!doctype html>
<html lang="id">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b1117;color:#e8eee9;font-family:Arial,Helvetica,sans-serif">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">Kode keamanan Algentra Capital Anda berlaku 10 menit.</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0b1117">
    <tr><td align="center" style="padding:34px 14px">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:560px">
        <tr><td style="padding:0 8px 20px">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
            <td width="42" height="42" align="center" valign="middle" style="border:1px solid #536d5e;border-radius:12px;background:#1a2823;color:#d4e5d9;font-size:13px;font-weight:800;letter-spacing:1px">AC</td>
            <td style="padding-left:12px;color:#e8eee9;font-size:14px;font-weight:700;letter-spacing:.4px">ALGENTRA CAPITAL<br><span style="color:#98a69f;font-size:10px;font-weight:400;letter-spacing:1px">AI-DRIVEN COPY TRADING</span></td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:1px;border:1px solid #30413a;border-radius:18px;background:#111a22">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr><td height="4" style="border-radius:18px 18px 0 0;background:#9fbea9;font-size:0;line-height:0">&nbsp;</td></tr>
            <tr><td style="padding:34px 34px 10px">
              <p style="margin:0 0 9px;color:#a8c7b2;font-size:10px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase">Kode keamanan akun</p>
              <h1 style="margin:0 0 12px;color:#edf3ee;font-size:25px;line-height:1.25;letter-spacing:-.4px">{safe_heading}</h1>
              <p style="margin:0;color:#aab6b0;font-size:14px;line-height:1.7">Gunakan kode di bawah untuk {safe_action} akun Algentra Capital Anda.</p>
            </td></tr>
            <tr><td style="padding:18px 34px 12px">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
                <td align="center" style="padding:20px 12px;border:1px solid #3e5549;border-radius:13px;background:#0c1519;color:#e5eee6;font-size:34px;font-weight:800;letter-spacing:10px;font-variant-numeric:tabular-nums">{safe_code}</td>
              </tr></table>
            </td></tr>
            <tr><td style="padding:0 34px 23px;text-align:center">
              <span style="display:inline-block;margin:5px;padding:6px 10px;border-radius:999px;background:#25332b;color:#c1d3c5;font-size:11px">Berlaku 10 menit</span>
              <span style="display:inline-block;margin:5px;padding:6px 10px;border-radius:999px;background:#25332b;color:#c1d3c5;font-size:11px">Sekali pakai</span>
            </td></tr>
            <tr><td style="padding:0 34px 30px">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
                <td style="padding:13px 15px;border-left:3px solid #c8b892;border-radius:5px;background:#201f1a;color:#d9d4c4;font-size:12px;line-height:1.65"><strong style="color:#eee3c4">Rahasiakan kode ini.</strong> Tim Algentra tidak akan meminta OTP Anda melalui telepon atau chat.</td>
              </tr></table>
              <p style="margin:18px 0 0;color:#899790;font-size:12px;line-height:1.65">Jika Anda tidak meminta kode ini, abaikan email ini. Akun Anda tetap aman.</p>
            </td></tr>
          </table>
        </td></tr>
        {social_html}
        <tr><td style="padding:19px 12px 0;color:#6f7d77;text-align:center;font-size:10px;line-height:1.7">
          Email otomatis untuk keamanan akun Anda.<br>Algentra Capital | Trading memiliki risiko; hasil historis bukan jaminan kinerja mendatang.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=10) as smtp:
        if settings.email_smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(settings.email_smtp_username, settings.email_smtp_password.get_secret_value())
        smtp.send_message(message)
