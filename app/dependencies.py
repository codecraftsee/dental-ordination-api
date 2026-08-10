from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.models.user import User
from app.permissions import ROLE_PERMISSIONS, Permission
from app.services.auth import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ModelT = TypeVar("ModelT", bound=Base)


def get_or_404(db: Session, model: type[ModelT], obj_id: str, name: str) -> ModelT:
    """Fetch a row by id, or raise the 404 the routers all used to spell out.

    `name` is the human label used in the message ("Patient" -> "Patient not
    found"), so each resource keeps the exact wording the frontend expects.
    """
    obj = db.query(model).filter(model.id == obj_id).first()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name} not found",
        )
    return obj


def apply_update(obj: Any, changes: dict) -> None:
    """Copy the explicitly-set fields of a Pydantic update model onto a row.

    `model_dump(exclude_unset=True)` keeps a field the client explicitly sent as
    null, so writing it straight through puts NULL into a NOT NULL column and
    surfaces as a 500. Reject it as a 400 naming the offending field instead.

    Fields are all validated before any are applied, so a rejected request never
    leaves the row half-updated.
    """
    columns = type(obj).__table__.columns
    for field, value in changes.items():
        if value is None:
            column = columns.get(field)
            if column is not None and not column.nullable:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Field '{field}' cannot be null",
                )

    for field, value in changes.items():
        setattr(obj, field, value)


def ensure_code_available(
    db: Session,
    model: type[ModelT],
    code: str,
    detail: str,
    exclude_id: str | None = None,
) -> None:
    """Reject a `code` already taken by another row.

    `detail` is passed in rather than derived, because create and update return
    different wording ("already exists" vs "already in use") and the frontend
    displays those strings.
    """
    query = db.query(model).filter(model.code == code)
    if exclude_id is not None:
        query = query.filter(model.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
        )

    return user


def require_permission(*permissions: Permission):
    def permission_checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        user_perms = ROLE_PERMISSIONS.get(current_user.role, frozenset())
        if not all(p in user_perms for p in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return current_user

    return permission_checker
