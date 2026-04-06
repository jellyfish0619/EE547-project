from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import get_current_user
from api.models import User
from api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from api.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    user = User(email=body.email, password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def read_me(current: User = Depends(get_current_user)):
    return current
