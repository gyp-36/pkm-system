"""Per-account encrypted DeepSeek connection; plaintext exists only during a call."""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Db, UserId
from app.enums import ModelProvider
from app.models import ModelConnection
from app.rate_limit import check_limit


router = APIRouter(prefix="/v1/model-connection", tags=["model-connection"])
log = logging.getLogger(__name__)
DEEPSEEK_URL = "https://api.deepseek.com"
KEY_ID = "local-v1"
ModelName = Literal["deepseek-flash", "deepseek-v4-pro"]


class ConnectionInput(BaseModel):
    api_key: SecretStr = Field(min_length=10, max_length=512)
    model_name: ModelName = "deepseek-flash"


class ConnectionTestInput(BaseModel):
    api_key: SecretStr | None = Field(default=None, min_length=10, max_length=512)
    model_name: ModelName | None = None


def cipher() -> Fernet:
    key = os.environ.get("PKM_CREDENTIAL_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="服务端密钥未配置")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="服务端密钥配置无效") from exc


def active_connection(db: Session, user_id: uuid.UUID, *, lock: bool = False) -> ModelConnection | None:
    query = select(ModelConnection).where(ModelConnection.user_id == user_id, ModelConnection.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def require_connection(db: Session, user_id: uuid.UUID) -> ModelConnection:
    row = active_connection(db, user_id)
    if row is None:
        raise HTTPException(status_code=409, detail="请先配置聊天模型连接")
    return row


def decrypt_key(row: ModelConnection) -> str:
    if row.credential_key_id != KEY_ID or not row.credential_ciphertext:
        raise HTTPException(status_code=503, detail="已保存密钥不可用，请重新配置")
    try:
        return cipher().decrypt(row.credential_ciphertext).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=503, detail="已保存密钥不可用，请重新配置") from exc


def chat_model(api_key: str, model_name: str, *, max_tokens: int = 700) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=DEEPSEEK_URL,
        timeout=45,
        max_retries=0,
        extra_body={"max_tokens": max_tokens, "thinking": {"type": "disabled"}},
    )


def public_connection(row: ModelConnection | None) -> dict:
    if row is None:
        return {"configured": False, "provider": None, "model_name": None, "key_masked": None, "updated_at": None}
    return {
        "configured": True,
        "provider": ModelProvider(row.provider).name.lower(),
        "model_name": row.model_name,
        "key_masked": "••••••••",
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("")
def get_connection(db: Db, user_id: UserId) -> dict:
    return public_connection(active_connection(db, user_id))


@router.put("")
def put_connection(body: ConnectionInput, db: Db, user_id: UserId) -> dict:
    encrypted = cipher().encrypt(body.api_key.get_secret_value().encode("utf-8"))
    row = active_connection(db, user_id, lock=True)
    if row is None:
        row = ModelConnection(
            user_id=user_id, provider=ModelProvider.DEEPSEEK, model_name=body.model_name,
            base_url=None, credential_ciphertext=encrypted, credential_key_id=KEY_ID,
        )
        db.add(row)
    else:
        row.model_name = body.model_name
        row.credential_ciphertext = encrypted
        row.credential_key_id = KEY_ID
    db.commit()
    db.refresh(row)
    return public_connection(row)


@router.post("/test")
def test_connection(body: ConnectionTestInput, db: Db, user_id: UserId) -> dict:
    row = active_connection(db, user_id)
    if body.api_key is None and row is None:
        raise HTTPException(status_code=404, detail="尚未配置模型连接")
    key = body.api_key.get_secret_value() if body.api_key is not None else decrypt_key(row)
    model_name = body.model_name or (row.model_name if row is not None else "deepseek-flash")
    check_limit(user_id, "connection_test", limit=5)
    try:
        result = chat_model(key, model_name, max_tokens=16).invoke("只回复：连接成功")
        if not str(result.content).strip():
            raise ValueError("empty model response")
    except Exception as exc:
        log.warning("model connection test failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="聊天模型连接失败，请检查 Key、额度和服务状态") from None
    return {"ok": True, "model_name": model_name}


@router.delete("", status_code=204)
def delete_connection(db: Db, user_id: UserId) -> None:
    row = active_connection(db, user_id, lock=True)
    if row is None:
        raise HTTPException(status_code=404, detail="尚未配置模型连接")
    row.credential_ciphertext = b""
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
