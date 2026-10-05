"""Exercise 0003 -> 0004 -> 0003 against an isolated disposable database."""

import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.ops.integrity import integrity_counts


def main() -> None:
    source = make_url(os.environ["DATABASE_URL"])
    test_name = f"pkm_migration_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = source.set(database=test_name)
    config = Config("/app/alembic.ini")
    original_url = os.environ["DATABASE_URL"]
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {test_name}"))
    try:
        os.environ["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
        command.upgrade(config, "0003_lifecycle_history_audit")
        test_engine = create_engine(target_url)
        with test_engine.begin() as connection:
            connection.execute(text("ALTER TABLE pkm_alembic_version RENAME TO alembic_version"))
            user_id, note_id, job_id, event_id, chunk_id = (uuid.uuid4() for _ in range(5))
            connection.execute(text("INSERT INTO accounts (id,email,password_hash) VALUES (:id,'migration@example.com','hash')"), {"id": user_id})
            connection.execute(text("INSERT INTO notes (id,user_id,title,body_md,version,index_status) VALUES (:id,:user_id,'标题','正文',1,'ready')"), {"id": note_id, "user_id": user_id})
            connection.execute(text("INSERT INTO note_chunks (id,user_id,note_id,note_version,ordinal,start_offset,end_offset,content,source) VALUES (:id,:user_id,:note_id,1,0,0,2,'正文','body')"), {"id": chunk_id, "user_id": user_id, "note_id": note_id})
            connection.execute(text("INSERT INTO index_jobs (id,user_id,note_id,target_version,status,attempts) VALUES (:id,:user_id,:note_id,1,'done',0)"), {"id": job_id, "user_id": user_id, "note_id": note_id})
            connection.execute(text("INSERT INTO audit_events (id,user_id,actor_type,action,entity_type,entity_id) VALUES (:id,:user_id,'user','create','note',:note_id)"), {"id": event_id, "user_id": user_id, "note_id": note_id})
        test_engine.dispose()

        command.upgrade(config, "0004_core_simplify")
        test_engine = create_engine(target_url)
        with test_engine.connect() as connection:
            tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'" )).scalars())
            assert len(tables) == 11 and all(name.startswith("pkm_") for name in tables), tables
            assert connection.scalar(text("SELECT count(*) FROM pg_constraint WHERE contype='f'")) == 0
            assert connection.scalar(text("SELECT index_status FROM pkm_notes WHERE id=:id"), {"id": note_id}) == 2
            assert connection.scalar(text("SELECT source FROM pkm_note_chunks WHERE id=:id"), {"id": chunk_id}) == 2
            assert connection.scalar(text("SELECT status FROM pkm_index_jobs WHERE id=:id"), {"id": job_id}) == 3
            assert connection.execute(text("SELECT actor_type,action,entity_type FROM pkm_audit_events WHERE id=:id"), {"id": event_id}).one() == (1, 4, 3)
            counts = connection.execute(text("SELECT tablename,count(*) FROM pg_indexes WHERE schemaname='public' AND tablename <> 'pkm_alembic_version' GROUP BY tablename")).all()
            assert len(counts) == 10 and all(2 <= count <= 3 for _, count in counts), counts
        test_engine.dispose()

        command.downgrade(config, "0003_lifecycle_history_audit")
        test_engine = create_engine(target_url)
        with test_engine.connect() as connection:
            assert connection.scalar(text("SELECT index_status FROM notes WHERE id=:id"), {"id": note_id}) == "ready"
            assert connection.scalar(text("SELECT count(*) FROM pg_constraint WHERE contype='f'")) == 11
        test_engine.dispose()

        command.upgrade(config, "head")
        test_engine = create_engine(target_url)
        with test_engine.connect() as connection:
            tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'" )).scalars())
            assert len(tables) == 12 and all(name.startswith("pkm_") for name in tables), tables
            counts = connection.execute(text("SELECT tablename,count(*) FROM pg_indexes WHERE schemaname='public' AND tablename <> 'pkm_alembic_version' GROUP BY tablename")).all()
            assert len(counts) == 11 and all(2 <= count <= 3 for _, count in counts), counts
            assert not any(integrity_counts(connection).values())
        with test_engine.begin() as connection:
            orphan_tag_id = uuid.uuid4()
            connection.execute(text("INSERT INTO pkm_note_tags (note_id,tag_id,user_id) VALUES (:note_id,:tag_id,:user_id)"), {"note_id": note_id, "tag_id": orphan_tag_id, "user_id": user_id})
            assert integrity_counts(connection)["note_tags_invalid_tag"] == 1
            connection.execute(text("DELETE FROM pkm_note_tags WHERE note_id=:note_id AND tag_id=:tag_id AND user_id=:user_id"), {"note_id": note_id, "tag_id": orphan_tag_id, "user_id": user_id})
        test_engine.dispose()
        command.downgrade(config, "0004_core_simplify")
        print("迁移 0003/0004/0005 的升级、枚举数据、索引预算、无外键约束、完整性检查和降级均已通过")
    finally:
        os.environ["DATABASE_URL"] = original_url
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE {test_name} WITH (FORCE)"))
        admin.dispose()


if __name__ == "__main__":
    main()
