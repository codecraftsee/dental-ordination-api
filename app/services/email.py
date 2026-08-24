import logging

import resend

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

resend.api_key = settings.resend_api_key

# The clinic's name, not the project's. Spam filters compare the sending domain
# against the name in the body, and "Dental Ordination" sent from
# smiletimeclinic.rs read as a mismatch — the first real invite went to Gmail's
# spam folder with SPF, DKIM and DMARC all passing.
CLINIC_NAME = "Smile Time Clinic"

# Why-you-got-this line. Transactional mail that explains itself scores better
# than mail that does not, and an unexpected "set your password" email is
# exactly the shape of a phishing attempt.
_REASON = (
    "You are receiving this email because your address was entered when the "
    "account was created. If you did not expect it, you can ignore this message."
)


def send_invite_email(to_email: str, first_name: str, set_password_url: str) -> None:
    logger.info("Sending invite email to %s via Resend", to_email)

    plain = (
        f"Hello {first_name},\n\n"
        f"An administrator has created a {CLINIC_NAME} account for you. "
        f"Open the link below to set your password:\n\n"
        f"{set_password_url}\n\n"
        f"This link expires in 48 hours.\n\n"
        f"{_REASON}\n\n"
        f"{CLINIC_NAME}"
    )

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
        <h2>Welcome to {CLINIC_NAME}</h2>
        <p>Hello <strong>{first_name}</strong>,</p>
        <p>An administrator has created a {CLINIC_NAME} account for you. Click the button
           below to set your password and activate it.</p>
        <p style="margin: 32px 0;">
          <a href="{set_password_url}"
             style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-size:15px;">
            Set My Password
          </a>
        </p>
        <p style="color:#666;font-size:13px;">This link expires in 48 hours.</p>
        <hr style="border:none;border-top:1px solid #e5e5e5;margin:32px 0 16px;">
        <p style="color:#888;font-size:12px;">
          {_REASON}<br><br>
          {CLINIC_NAME}
        </p>
      </body>
    </html>
    """

    params: resend.Emails.SendParams = {
        "from": settings.email_from,
        "to": [to_email],
        "subject": f"Welcome to {CLINIC_NAME} — set your password",
        "text": plain,
        "html": html,
    }

    response = resend.Emails.send(params)
    logger.info("Invite email sent successfully to %s: id=%s", to_email, response["id"])
