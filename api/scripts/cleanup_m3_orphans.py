"""Back up and remove M3 rows whose account no longer exists.

Run without --apply for a read-only inventory. Applying writes a durable archive
inside the note-files volume before deleting database rows or stored objects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.core import object_storage
from app.core.db import engine
from app.knowledge.m3 import FILE_ROOT


def _records(connection, query: str, params: dict | None = None) -> list[dict]:
    return [dict(row._mapping) for row in connection.execute(text(query), params or {})]


def collect(connection) -> dict:
    versions = _records(connection, """
        SELECT f.* FROM pkm_note_file_versions f
        LEFT JOIN pkm_accounts a ON a.id=f.user_id
        LEFT JOIN pkm_notes n ON n.id=f.note_id AND n.user_id=f.user_id
        WHERE a.id IS NULL OR n.id IS NULL ORDER BY f.created_at, f.id
    """)
    drafts = _records(connection, """
        SELECT d.* FROM pkm_link_drafts d
        LEFT JOIN pkm_accounts a ON a.id=d.user_id
        WHERE a.id IS NULL ORDER BY d.created_at, d.id
    """)
    text_blocks = _records(connection, """
        SELECT x.* FROM pkm_note_text_blocks x
        LEFT JOIN pkm_accounts a ON a.id=x.user_id
        LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id
        WHERE a.id IS NULL OR n.id IS NULL ORDER BY x.note_id, x.content_version, x.ordinal
    """)
    version_ids = [str(row["id"]) for row in versions]
    if version_ids:
        jobs = _records(connection, """
            SELECT j.* FROM pkm_file_ingest_jobs j
            WHERE j.file_version_id = ANY(CAST(:ids AS uuid[])) ORDER BY j.id
        """, {"ids": version_ids})
    else:
        jobs = []
    return {"file_versions": versions, "file_ingest_jobs": jobs, "link_drafts": drafts, "text_blocks": text_blocks}


def backup_objects(archive: zipfile.ZipFile, manifest: dict) -> list[Path]:
    delete_paths: list[Path] = []
    manifest["objects"] = []
    for row in manifest["file_versions"]:
        key = row["storage_key"]
        item = {"storage_key": key, "storage_backend": row["storage_backend"], "backed_up": False}
        try:
            if row["storage_backend"] == "s3":
                content = object_storage.get(key)
            elif row["storage_backend"] == "filesystem":
                path = FILE_ROOT / key[:2] / key
                if not path.is_file():
                    item["missing"] = True
                    manifest["objects"].append(item)
                    continue
                content = path.read_bytes()
                delete_paths.append(path)
            else:
                raise RuntimeError(f"unsupported storage backend: {row['storage_backend']}")
        except Exception as exc:
            item["missing"] = True
            item["error"] = type(exc).__name__
            manifest["objects"].append(item)
            continue
        archive.writestr(f"objects/{key}", content)
        item.update({"backed_up": True, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        manifest["objects"].append(item)
    return delete_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="back up and delete confirmed orphan M3 rows")
    parser.add_argument("--backup-dir", type=Path, default=FILE_ROOT / ".orphan-backups")
    args = parser.parse_args()

    with engine.connect() as connection:
        manifest = collect(connection)
    counts = {name: len(rows) for name, rows in manifest.items()}
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "counts": counts}, ensure_ascii=False, indent=2, default=str))
    if not args.apply:
        return

    total = sum(counts.values())
    if total == 0:
        print("没有待清理的 M3 孤儿记录")
        return

    args.backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = args.backup_dir / f"m3-orphans-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    delete_paths: list[Path] = []
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, rows in manifest.items():
            if name != "objects":
                archive.writestr(f"records/{name}.json", json.dumps(rows, ensure_ascii=False, default=str, indent=2))
        delete_paths = backup_objects(archive, manifest)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, default=str, indent=2))
    if any(item.get("missing") and item["storage_backend"] == "s3" for item in manifest["objects"]):
        raise RuntimeError(f"对象存储文件无法备份，未删除数据库记录；清单已保存到 {backup_path}")

    # Recheck the account-orphan predicates inside the deleting transaction so
    # rows that were repaired while the archive was being written are retained.
    with engine.begin() as connection:
        version_ids = [row["id"] for row in manifest["file_versions"]]
        draft_ids = [row["id"] for row in manifest["link_drafts"]]
        text_block_ids = [row["id"] for row in manifest["text_blocks"]]
        version_ids = connection.execute(text("""
            SELECT f.id FROM pkm_note_file_versions f
            LEFT JOIN pkm_accounts a ON a.id=f.user_id
            LEFT JOIN pkm_notes n ON n.id=f.note_id AND n.user_id=f.user_id
            WHERE f.id = ANY(CAST(:ids AS uuid[])) AND (a.id IS NULL OR n.id IS NULL)
        """), {"ids": [str(value) for value in version_ids]}).scalars().all() if version_ids else []
        draft_ids = connection.execute(text("""
            SELECT d.id FROM pkm_link_drafts d
            LEFT JOIN pkm_accounts a ON a.id=d.user_id
            WHERE d.id = ANY(CAST(:ids AS uuid[])) AND a.id IS NULL
        """), {"ids": [str(value) for value in draft_ids]}).scalars().all() if draft_ids else []
        text_block_ids = connection.execute(text("""
            SELECT x.id FROM pkm_note_text_blocks x
            LEFT JOIN pkm_accounts a ON a.id=x.user_id
            LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id
            WHERE x.id = ANY(CAST(:ids AS uuid[])) AND (a.id IS NULL OR n.id IS NULL)
        """), {"ids": [str(value) for value in text_block_ids]}).scalars().all() if text_block_ids else []
        if version_ids:
            connection.execute(text("DELETE FROM pkm_file_ingest_jobs WHERE file_version_id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(value) for value in version_ids]})
            connection.execute(text("DELETE FROM pkm_note_file_versions WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(value) for value in version_ids]})
        if draft_ids:
            connection.execute(text("DELETE FROM pkm_link_drafts WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(value) for value in draft_ids]})
        if text_block_ids:
            connection.execute(text("DELETE FROM pkm_note_text_blocks WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(value) for value in text_block_ids]})

    for path in delete_paths:
        path.unlink(missing_ok=True)
    for row in manifest["file_versions"]:
        if row["storage_backend"] == "s3" and next((item["backed_up"] for item in manifest["objects"] if item["storage_key"] == row["storage_key"]), False):
            object_storage.delete(row["storage_key"])

    print(json.dumps({"backup": str(backup_path), "deleted_counts": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
