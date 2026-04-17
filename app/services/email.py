import logging
import mailtrap as mt
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def send_invite_email(to_email: str, first_name: str, set_password_url: str) -> None:
    logger.info("Sending invite email to %s via Mailtrap API (inbox_id=%s)", to_email, settings.mailtrap_inbox_id or "production")

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

    mail = mt.Mail(
        sender=mt.Address(email=settings.smtp_from, name="Dental Ordination"),
        to=[mt.Address(email=to_email)],
        subject="Welcome to Dental Ordination — Set Your Password",
        text=plain,
        html=html,
    )

    sandbox = bool(settings.mailtrap_inbox_id)
    client = mt.MailtrapClient(
        token=settings.mailtrap_api_token,
        sandbox=sandbox,
        **({"inbox_id": int(settings.mailtrap_inbox_id)} if sandbox else {}),
    )

    response = client.send(mail)
    logger.info("Invite email sent successfully to %s: %s", to_email, response)
