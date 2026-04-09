import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import get_settings

settings = get_settings()


def send_invite_email(to_email: str, first_name: str, set_password_url: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Welcome to Dental Ordination — Set Your Password"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    plain = (
        f"Hello {first_name},\n\n"
        f"Your account has been created. Click the link below to set your password:\n\n"
        f"{set_password_url}\n\n"
        f"This link expires in 48 hours.\n\n"
        f"If you did not expect this email, please ignore it."
    )

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
        <h2>Welcome to Dental Ordination</h2>
        <p>Hello <strong>{first_name}</strong>,</p>
        <p>Your account has been created. Click the button below to set your password and activate your account.</p>
        <p style="margin: 32px 0;">
          <a href="{set_password_url}"
             style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-size:15px;">
            Set My Password
          </a>
        </p>
        <p style="color:#666;font-size:13px;">This link expires in 48 hours. If you did not expect this email, please ignore it.</p>
      </body>
    </html>
    """

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, to_email, msg.as_string())
