from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.services.auth import create_invite_token
from app.services.email import send_invite_email
from app.dependencies import require_admin
from app.config import get_settings

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        must_set_password=user.must_set_password,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        specialization=user.specialization,
        license_number=user.license_number,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("", response_model=List[UserResponse])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    role: Optional[UserRole] = Query(None),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    return [_to_response(u) for u in query.all()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
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
    send_invite_email(user.email, data.first_name, invite_url)

    return _to_response(user)


@router.post("/{user_id}/resend-invite", status_code=status.HTTP_204_NO_CONTENT)
def resend_invite(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.must_set_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has already set their password")

    settings = get_settings()
    token = create_invite_token(user.id)
    invite_url = f"{settings.frontend_url}/set-password?token={token}"
    first_name = user.first_name or user.email
    send_invite_email(user.email, first_name, invite_url)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_response(user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    data: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update = data.model_dump(exclude_unset=True)

    if "email" in update:
        if db.query(User).filter(User.email == update["email"], User.id != user_id).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already in use")

    for key, value in update.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return _to_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)]
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db.delete(user)
    db.commit()
