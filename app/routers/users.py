import logging
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate, UserResponse, to_user_response
from app.services.auth import create_invite_token
from app.services.email import send_invite_email
from app.dependencies import apply_update, get_or_404, require_permission
from app.permissions import Permission
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[UserResponse])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission(Permission.USERS_READ))],
    role: Optional[UserRole] = Query(None),
):
    query = db.query(User).filter(User.is_active == True)
    if current_user.role != UserRole.ADMIN:
        query = query.filter(User.role != UserRole.ADMIN)
    if role:
        query = query.filter(User.role == role)
    return [to_user_response(u) for u in query.all()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.USERS_CREATE))]
):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=data.email,
        role=data.role,
        must_set_password=True,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        specialization=data.specialization,
        license_number=data.license_number,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    settings = get_settings()
    token = create_invite_token(user.id)
    invite_url = f"{settings.frontend_url}/set-password?token={token}"
    try:
        send_invite_email(user.email, data.first_name, invite_url)
    except Exception as exc:
        logger.error("Failed to send invite email to %s: %s", user.email, exc)

    return to_user_response(user)


@router.post("/{user_id}/resend-invite", status_code=status.HTTP_204_NO_CONTENT)
def resend_invite(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.USERS_CREATE))]
):
    user = get_or_404(db, User, user_id, "User")
    if not user.must_set_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has already set their password")

    settings = get_settings()
    token = create_invite_token(user.id)
    invite_url = f"{settings.frontend_url}/set-password?token={token}"
    first_name = user.first_name or user.email
    try:
        send_invite_email(user.email, first_name, invite_url)
    except Exception as exc:
        logger.error("Failed to resend invite email to %s: %s", user.email, exc)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.USERS_READ))]
):
    return to_user_response(get_or_404(db, User, user_id, "User"))


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    data: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.USERS_UPDATE))]
):
    user = get_or_404(db, User, user_id, "User")

    update = data.model_dump(exclude_unset=True)

    if "email" in update:
        if db.query(User).filter(User.email == update["email"], User.id != user_id).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already in use")

    apply_update(user, update)
    db.commit()
    db.refresh(user)
    return to_user_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_permission(Permission.USERS_DELETE))]
):
    user = get_or_404(db, User, user_id, "User")
    user.is_active = False
    db.commit()
