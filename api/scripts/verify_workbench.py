"""验证工作台模块预览的上限、排序和账号隔离；结束后清理临时账号。"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.core.models import DigestRun, Note, NoteReminder
from app.main import app
from app.ops.maintenance import purge_accounts


def main() -> None:
    account_ids = []
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            for client in (alice, bob):
                response = client.post("/v1/auth/register", json={
                    "email": f"workbench-{uuid.uuid4().hex[:12]}@example.com",
                    "password": "TestPassword123!",
                })
                assert response.status_code == 201, response.text
                account_ids.append(uuid.UUID(response.json()["id"]))
            empty = alice.get("/v1/workbench").json()
            assert empty["reminders"] == empty["archive"] == []
            assert empty["latest_daily"] is None and empty["latest_weekly"] is None and empty["recent_note"] is None

            now = datetime.now(timezone.utc)
            with SessionLocal.begin() as db:
                recent = Note(user_id=account_ids[0], title="最近编辑的笔记", updated_at=now,
                              body_md="# 周报\n\n## 本周概览\n完成检索实验记录。[S1](#/notes?note=example)\n\n### 混合检索\n比较检索结果。")
                older = Note(user_id=account_ids[0], title="旧笔记", updated_at=now - timedelta(days=1))
                daily_note = Note(user_id=account_ids[0], title="日报｜阅读记录", updated_at=now - timedelta(minutes=1),
                                  body_md="# 日报\n\n## 今日记录\n记下今天的阅读发现。[S2]\n\n### 阅读摘录\n留下新的线索。")
                foreign = Note(user_id=account_ids[1], title="别人的内容", updated_at=now + timedelta(hours=1), deleted_at=now - timedelta(days=29, hours=1))
                db.add_all([recent, older, daily_note, foreign])
                db.flush()
                recent_id = str(recent.id)
                # 最近删除的 101 条占满普通归档首页，概览仍应取全库最早清除的三条。
                db.add_all([Note(user_id=account_ids[0], title=f"新归档 {i}", deleted_at=now)
                            for i in range(101)])
                expiring = [Note(user_id=account_ids[0], title=f"即将清除 {i}", deleted_at=now - timedelta(days=29-i))
                            for i in range(3)]
                db.add_all(expiring)
                db.flush()
                past = [NoteReminder(user_id=account_ids[0], text=f"到期提醒 {i}", due_at=now - timedelta(hours=6-i))
                        for i in range(6)]
                future = [NoteReminder(user_id=account_ids[0], text=f"未来提醒 {i}", due_at=now + timedelta(hours=i+1))
                          for i in range(4)]
                db.add_all(past + future + [
                    NoteReminder(user_id=account_ids[0], text="已完成", status="done", due_at=now - timedelta(days=2)),
                    NoteReminder(user_id=account_ids[0], note_id=expiring[0].id, text="来源已归档", due_at=now - timedelta(days=3)),
                    NoteReminder(user_id=account_ids[1], text="他人的提醒", due_at=now - timedelta(days=4)),
                ])
                runs = [DigestRun(user_id=account_ids[0], kind=kind, slot_key=uuid.uuid4().hex[:16],
                                  scheduled_at=now - timedelta(hours=hours), period_start=now - timedelta(days=7),
                                  period_end=now, status="ready", note_id=daily_note.id if kind == "daily" else recent.id)
                        for kind, hours in [("weekly", 2), ("weekly", 1), ("daily", 3), ("daily", 0)]]
                db.add_all(runs)
                db.flush()
                expiring_ids = [str(note.id) for note in expiring]
                past_ids = [str(item.id) for item in past]
                future_ids = [str(item.id) for item in future]
                latest_id = str(runs[1].id)
                latest_uuid = runs[1].id
                daily_id = str(runs[3].id)
                daily_uuid = runs[3].id
                daily_note_id = str(daily_note.id)
                past_uuids = [item.id for item in past]

            response = alice.get("/v1/workbench")
            assert response.status_code == 200, response.text
            overview = response.json()
            assert [item["id"] for item in overview["reminders"]] == past_ids[:3]
            assert [item["id"] for item in overview["archive"]] == expiring_ids
            assert overview["latest_weekly"]["id"] == latest_id  # 不被五条到期提醒或日报挤掉。
            assert overview["latest_weekly"]["note_active"] is True
            assert overview["latest_daily"]["id"] == daily_id
            assert overview["latest_daily"]["kind"] == "daily"
            assert overview["latest_weekly"]["kind"] == "weekly"
            assert overview["latest_daily"]["note_id"] == daily_note_id
            assert overview["latest_weekly"]["note_id"] == recent_id
            assert overview["latest_daily"]["excerpt"].startswith("记下今天的阅读发现。")
            assert overview["latest_daily"]["topics"] == ["阅读摘录"]
            assert overview["latest_weekly"]["topics"] == ["混合检索"]
            assert "S1" not in overview["latest_weekly"]["excerpt"]
            assert "#/notes" not in overview["latest_weekly"]["excerpt"]
            assert overview["recent_note"]["id"] == recent_id
            assert len(overview["items"]) == 5  # 保留旧响应兼容性。
            foreign_overview = bob.get("/v1/workbench").json()
            assert foreign_overview["latest_weekly"] is None
            assert foreign_overview["latest_daily"] is None
            assert all(item["id"] not in expiring_ids for item in foreign_overview["archive"])
            assert bob.patch(f"/v1/reminders/{past_ids[0]}", json={"status": "done"}).status_code == 404
            assert alice.patch(f"/v1/reminders/{past_ids[0]}", json={"status": "done"}).status_code == 200
            completed = alice.get("/v1/workbench").json()
            assert [item["id"] for item in completed["reminders"]] == past_ids[1:4]

            with SessionLocal.begin() as db:
                for item_id in past_uuids:
                    db.get(NoteReminder, item_id).status = "done"
                db.get(Note, uuid.UUID(recent_id)).deleted_at = now
            refreshed = alice.get("/v1/workbench").json()
            assert [item["id"] for item in refreshed["reminders"]] == future_ids[:3]
            assert refreshed["latest_weekly"]["note_archived"] is True
            assert refreshed["latest_weekly"]["note_active"] is False
            assert refreshed["latest_daily"]["note_active"] is True
            assert refreshed["recent_note"]["id"] != recent_id
            with SessionLocal.begin() as db:
                run = db.get(DigestRun, latest_uuid)
                run.status = "failed"
                run.note_id = None
            assert alice.get("/v1/workbench").json()["latest_weekly"]["status"] == "failed"
            assert alice.get("/v1/workbench").json()["latest_daily"]["id"] == daily_id
            with SessionLocal.begin() as db:
                db.get(DigestRun, daily_uuid).status = "processing"
                db.get(DigestRun, daily_uuid).note_id = None
            processing = alice.get("/v1/workbench").json()
            assert processing["latest_daily"]["status"] == "processing"
            assert processing["latest_daily"]["excerpt"] == ""
            assert processing["latest_daily"]["topics"] == []
            assert processing["latest_weekly"]["status"] == "failed"
            print("工作台预览上限、日报/周报独立排序与正文、真实主题、生成状态、归档状态及双账号隔离通过")
    finally:
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
