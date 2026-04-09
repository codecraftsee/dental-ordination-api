from app.models.user import User


def profile_fields(user: User) -> dict:
    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "specialization": user.specialization,
        "license_number": user.license_number,
    }
