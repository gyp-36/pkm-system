"""Copy filesystem-backed note files into S3 and verify bytes before switching rows."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import NoteFileVersion
from app.core.object_storage import ensure_bucket, get, hash_object, put


FILE_ROOT = Path(os.getenv("NOTE_FILE_ROOT", "/data/note-files"))


def main() -> int:
    ensure_bucket()
    migrated = 0
    with SessionLocal() as db:
        rows = db.scalars(select(NoteFileVersion).where(NoteFileVersion.storage_backend == "filesystem").order_by(NoteFileVersion.created_at)).all()
        for row in rows:
            if not re.fullmatch(r"[0-9a-f-]{36}", row.storage_key):
                print(f"无效的对象键：{row.id}", file=sys.stderr)
                return 1
            path = FILE_ROOT / row.storage_key[:2] / row.storage_key
            if not path.is_file():
                print(f"本地文件不存在：{row.id}", file=sys.stderr)
                return 1
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if len(content) != row.size_bytes or digest != row.sha256:
                print(f"本地校验和不匹配：{row.id}", file=sys.stderr)
                return 1
            try:
                remote_digest, remote_size = hash_object(row.storage_key)
            except Exception:
                put(row.storage_key, content, row.media_type)
                remote_digest, remote_size = hash_object(row.storage_key)
            if remote_size != row.size_bytes or remote_digest != row.sha256:
                put(row.storage_key, content, row.media_type)
                remote_digest, remote_size = hash_object(row.storage_key)
            if remote_size != row.size_bytes or remote_digest != row.sha256:
                print(f"对象存储校验失败：{row.id}", file=sys.stderr)
                return 1
            row.storage_backend = "s3"
            db.commit()
            migrated += 1
            print(f"已迁移 {row.id} {row.filename}")
    print(f"迁移完成：共迁移 {migrated} 个文件版本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
