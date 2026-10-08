"""Revocable, account-scoped sessions stored as token hashes."""

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Generator

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event, record_failure_isolated
from app.core.models import Account, UserSession
from app.contracts.auth import AccountOut


router = APIRouter(prefix="/v1/auth", tags=["auth"])
password_hasher = PasswordHasher()
SESSION_DAYS = 7
COOKIE_NAME = "pkm_session"
session_cookie = APIKeyCookie(name=COOKIE_NAME, scheme_name="PKMSession", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db


Db = Annotated[Session, Depends(get_db)]


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def add_session(db: Session, account: Account, response: Response) -> None:
    token = secrets.token_urlsafe(48)
    db.add(
        UserSession(
            user_id=account.id,
            token_hash=token_digest(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "0") == "1",
        samesite="lax",
        path="/",
    )


def get_current_user_id(
    db: Db,
    token: Annotated[str | None, Depends(session_cookie)],
) -> uuid.UUID:
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    record = db.scalar(
        select(UserSession).join(Account, Account.id == UserSession.user_id).where(
            UserSession.token_hash == token_digest(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(timezone.utc),
            Account.deleted_at.is_(None),
        )
    )
    if record is None:
        raise HTTPException(status_code=401, detail="登录已失效")
    return record.user_id


UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]


def account_json(account: Account) -> dict[str, str]:
    return {"id": str(account.id), "email": account.email}


@router.post("/register", status_code=201, response_model=AccountOut)
def register(body: Credentials, response: Response, db: Db) -> dict[str, str]:
    email = str(body.email).lower()
    account = Account(email=email, password_hash=password_hasher.hash(body.password))
    db.add(account)
    try:
        db.flush()
        record_event(db, account.id, AuditAction.REGISTER, AuditEntityType.ACCOUNT, account.id)
        add_session(db, account, response)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="邮箱已注册") from exc
    return account_json(account)


@router.post("/login", response_model=AccountOut)
def login(body: Credentials, response: Response, db: Db) -> dict[str, str]:
    account = db.scalar(select(Account).where(Account.email == str(body.email).lower(), Account.deleted_at.is_(None)))
    if account is None:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    try:
        password_hasher.verify(account.password_hash, body.password)
    except (VerificationError, InvalidHashError) as exc:
        # 密码错误不留业务痕迹是安全盲区（暴力破解无法追溯）。
        # 此时请求没有有效会话 Cookie，中间件无法归属用户，故在此独立补记。
        record_failure_isolated(
            user_id=account.id,
            action=AuditAction.LOGIN,
            entity_type=AuditEntityType.ACCOUNT,
            entity_id=account.id,
            details={"reason": "bad_credentials"},
        )
        raise HTTPException(status_code=401, detail="邮箱或密码错误") from exc
    if password_hasher.check_needs_rehash(account.password_hash):
        account.password_hash = password_hasher.hash(body.password)
    record_event(db, account.id, AuditAction.LOGIN, AuditEntityType.ACCOUNT, account.id)
    add_session(db, account, response)
    return account_json(account)


@router.post("/logout", status_code=204)
def logout(response: Response, db: Db, user_id: UserId, token: Annotated[str | None, Depends(session_cookie)]) -> None:
    record = db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(token or ""), UserSession.user_id == user_id))
    if record is not None:
        record.revoked_at = datetime.now(timezone.utc)
        record_event(db, user_id, AuditAction.LOGOUT, AuditEntityType.SESSION, record.id)
        db.commit()
    response.delete_cookie(key=COOKIE_NAME, path="/", samesite="lax")


@router.get("/me", response_model=AccountOut)
def me(db: Db, user_id: UserId) -> dict[str, str]:
    account = db.get(Account, user_id)
    if account is None or account.deleted_at is not None:
        raise HTTPException(status_code=401, detail="登录已失效")
    return account_json(account)
