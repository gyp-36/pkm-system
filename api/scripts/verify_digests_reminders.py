"""Disposable acceptance check for scheduled reports and note reminders."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.assistant.digests import _section, _verified_body, collect_evidence, enqueue_due, next_occurrence, process_run
from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType
from app.core.models import AuditEvent, DigestRun, Note, NoteReminder
from app.main import app
from app.ops.maintenance import purge_accounts


def call(client: TestClient, method: str, path: str, status: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == status, (method, path, response.status_code, response.text[:700])
    return response.json() if response.content else None


class FakeModel:
    def invoke(self, messages):
        assert "笔记回顾助手" in messages[0].content
        assert "S1" in messages[1].content
        return SimpleNamespace(content="# 日报\n\n## 今日记录\n- 修改了笔记 [S1]\n")


def check_source_markers() -> None:
    """[S编号] 只做内部键：渲染成来源标题链接，区间和裸编号一律判为无效输出。"""
    refs = [
        {"citation": "S1", "note_id": "11111111-1111-1111-1111-111111111111", "note_version": 1, "title": "甲笔记"},
        {"citation": "S2", "note_id": "22222222-2222-2222-2222-222222222222", "note_version": 2, "title": "乙[笔记]"},
    ]
    rendered = _verified_body("## 本期\n- 结论 [S1][S2]\n", refs)
    assert "S1" not in rendered and "S2" not in rendered
    assert ("[甲笔记](#/notes?note=11111111-1111-1111-1111-111111111111)、"
            "[乙\\[笔记\\]](#/notes?note=22222222-2222-2222-2222-222222222222)") in rendered
    for bad in ("- 结论 [S1]-[S2]\n", "- 结论 [S1]—[S2]\n", "- 结论 [S1]，另外见 S2\n",
                "- 依据 S1-S2 的合并写法 [S1]\n", "- 结论 [S9]\n",
                "- 结论没有来源\n", "## 本期\n没有标记\n"):
        try:
            _verified_body(bad, refs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝不合规来源标注：{bad}")


def main() -> None:
    ids: list[uuid.UUID] = []
    check_source_markers()
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            suffix = uuid.uuid4().hex[:10]
            a = call(alice, "POST", "/v1/auth/register", 201, json={"email": f"digest-a-{suffix}@example.com", "password": "TestPassword123!"})
            b = call(bob, "POST", "/v1/auth/register", 201, json={"email": f"digest-b-{suffix}@example.com", "password": "TestPassword123!"})
            ids = [uuid.UUID(a["id"]), uuid.UUID(b["id"])]
            assert call(alice, "GET", "/v1/digests/settings", 200)["daily_enabled"] is False
            assert next_occurrence("weekly", after=datetime(2026, 10, 4, 12, tzinfo=timezone.utc), at_time="21:00", weekday=6).astimezone(timezone(timedelta(hours=8))).day == 4
            call(alice, "PUT", "/v1/model-connection", 200, json={"api_key": "sk-local-fake-secret", "model_name": "deepseek-flash"})
            settings = call(alice, "PUT", "/v1/digests/settings", 200, json={"daily_enabled": True, "daily_time": "21:00", "weekly_enabled": True, "weekly_weekday": 6, "weekly_time": "22:00"})
            assert settings["daily_next_at"] and settings["weekly_next_at"]
            weekly_settings = call(alice, "PATCH", "/v1/digests/settings", 200, json={"weekly_weekday": 4, "weekly_time": "19:30"})
            assert weekly_settings["daily_enabled"] and weekly_settings["daily_time"] == "21:00"
            assert weekly_settings["weekly_weekday"] == 4 and weekly_settings["weekly_time"] == "19:30"
            daily_settings = call(alice, "PATCH", "/v1/digests/settings", 200, json={"daily_time": "20:45"})
            assert daily_settings["weekly_weekday"] == 4 and daily_settings["weekly_time"] == "19:30"
            assert call(bob, "PUT", "/v1/digests/settings", 200, json={"daily_enabled": True, "daily_time": "20:00"})["daily_enabled"]
            note = call(alice, "POST", "/v1/notes", 201, json={"title": "本人的素材", "body_md": "最初记录"})
            other = call(bob, "POST", "/v1/notes", 201, json={"title": "他人的素材", "body_md": "不能引用"})
            note = call(alice, "PATCH", f"/v1/notes/{note['id']}", 200, json={"version": note["version"], "body_md": "更新后的记录"})
            tag = call(alice, "POST", "/v1/tags", 201, json={"name": "报告分类"})
            note = call(alice, "PATCH", f"/v1/notes/{note['id']}", 200, json={"version": note["version"], "tag_ids": [tag["id"]]})
            due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            reminder = call(alice, "POST", f"/v1/notes/{note['id']}/reminders", 201, json={"text": "检查记录", "due_at": due})
            standalone = call(alice, "POST", "/v1/reminders", 201, json={"text": "独立事项", "due_at": due})
            assert standalone["note_id"] is None and standalone["note_title"] is None
            linked_new_api = call(alice, "POST", "/v1/reminders", 201, json={"text": "新接口关联", "due_at": due, "note_id": note["id"]})
            assert linked_new_api["note_id"] == note["id"]
            call(bob, "POST", "/v1/reminders", 404, json={"text": "越权关联", "due_at": due, "note_id": note["id"]})
            call(bob, "POST", f"/v1/notes/{note['id']}/reminders", 404, json={"text": "越权", "due_at": due})
            call(bob, "PATCH", f"/v1/reminders/{reminder['id']}", 404, json={"status": "done"})
            assert call(bob, "GET", "/v1/reminders", 200)["items"] == []
            assert any(item["id"] == standalone["id"] and item["note_id"] is None for item in call(alice, "GET", "/v1/workbench", 200)["items"])
            assert any(item["id"] == standalone["id"] for item in call(alice, "GET", "/v1/reminders?status=all", 200)["items"])
            first_page = call(alice, "GET", "/v1/reminders?status=all&limit=1", 200)
            assert len(first_page["items"]) == 1 and first_page["next_offset"] == 1
            assert len(call(alice, "GET", "/v1/reminders?status=all&limit=1&offset=1", 200)["items"]) == 1
            call(alice, "PATCH", f"/v1/reminders/{reminder['id']}", 200, json={"status": "done"})
            assert all(item["id"] != reminder["id"] for item in call(alice, "GET", "/v1/workbench", 200)["items"])
            call(alice, "PATCH", f"/v1/reminders/{reminder['id']}", 200, json={"status": "open", "due_at": due})
            call(alice, "PATCH", f"/v1/reminders/{standalone['id']}", 200, json={"status": "done"})
            assert any(item["id"] == standalone["id"] and item["status"] == "done" for item in call(alice, "GET", "/v1/reminders?status=all", 200)["items"])
            call(alice, "PATCH", f"/v1/reminders/{standalone['id']}", 200, json={"status": "open", "due_at": due})

            now = datetime.now(timezone.utc)
            with SessionLocal.begin() as db:
                run = DigestRun(user_id=ids[0], kind="daily", slot_key="test-" + suffix,
                                scheduled_at=now + timedelta(seconds=1), period_start=now - timedelta(days=1),
                                period_end=now + timedelta(seconds=1), status="processing", attempts=1)
                db.add(run)
                db.flush()
                run_id = run.id
            with SessionLocal() as db:
                activities, _, _ = collect_evidence(db, db.get(DigestRun, run_id))
                assert any("classification_changed" in item["actions"] for item in activities)
                assert all("独立事项" not in str(item) for item in activities)
            with patch("app.assistant.digests.chat_model", return_value=FakeModel()):
                process_run(run_id)
                process_run(run_id)
            report = call(alice, "GET", f"/v1/digests", 200)["items"][0]
            assert report["status"] == "ready" and report["note_id"]
            assert call(alice, "GET", "/v1/digests?kind=weekly&limit=1&offset=0", 200)["items"] == []
            assert all(item["kind"] == "daily" and item["note_active"] and not item["note_archived"] for item in call(alice, "GET", "/v1/digests?kind=daily&limit=1", 200)["items"])
            assert _section(SimpleNamespace(kind="daily", scheduled_at=datetime(2026, 10, 4, 13, tzinfo=timezone.utc)), datetime(2026, 10, 3, 15, tzinfo=timezone.utc)) == "前一日晚间补记"
            with SessionLocal() as db:
                assert len(db.scalars(select(Note.id).where(Note.user_id == ids[0], Note.title.like("日报｜%"))).all()) == 1
            body = call(alice, "GET", f"/v1/notes/{report['note_id']}", 200)
            assert f"[本人的素材](#/notes?note={note['id']})" in body["body_md"]
            assert "#/notes?note=" in body["body_md"]
            assert "S1" not in body["body_md"]
            assert other["id"] not in body["body_md"]
            assert call(bob, "GET", f"/v1/notes/{report['note_id']}", 404) is not None
            body = call(alice, "PATCH", f"/v1/notes/{body['id']}", 200, json={"version": body["version"], "body_md": body["body_md"] + "\n人工补充"})
            assert "人工补充" in body["body_md"]
            note = call(alice, "PATCH", f"/v1/notes/{note['id']}", 200, json={"version": note["version"], "body_md": "再次补充来源"})
            assert call(alice, "GET", f"/v1/notes/{report['note_id']}", 200)["digest_sources_changed"] == 1
            with SessionLocal() as db:
                future = DigestRun(user_id=ids[0], kind="daily", slot_key="future", scheduled_at=datetime.now(timezone.utc) + timedelta(seconds=1),
                                   period_start=now + timedelta(seconds=1), period_end=datetime.now(timezone.utc) + timedelta(seconds=2))
                activities, refs, _ = collect_evidence(db, future)
                assert all(ref["note_id"] != report["note_id"] for ref in refs)
            assert call(alice, "GET", "/v1/workbench", 200)["items"][0]["kind"] == "reminder"
            call(alice, "DELETE", f"/v1/reminders/{reminder['id']}", 204)
            assert all(item["id"] != reminder["id"] for item in call(alice, "GET", "/v1/reminders", 200)["items"])
            with SessionLocal.begin() as db:
                failed = DigestRun(user_id=ids[0], kind="weekly", slot_key="test-" + suffix,
                                   scheduled_at=now, period_start=now - timedelta(days=7), period_end=now,
                                   status="failed", error="模型失败", attempts=1)
                db.add(failed)
                db.flush()
                failed_id = failed.id
            call(bob, "POST", f"/v1/digests/{failed_id}/retry", 404)
            weekly_page = call(alice, "GET", "/v1/digests?kind=weekly&limit=1&offset=0", 200)
            assert len(weekly_page["items"]) == 1 and weekly_page["items"][0]["status"] == "failed"
            assert call(bob, "GET", "/v1/digests?kind=weekly", 200)["items"] == []
            call(alice, "POST", f"/v1/digests/{failed_id}/retry", 200)
            assert any(item.get("status") == "ready" for item in call(alice, "GET", "/v1/workbench", 200)["items"])
            with SessionLocal.begin() as db:
                missing_model = DigestRun(user_id=ids[1], kind="daily", slot_key="test-" + suffix,
                                          scheduled_at=now, period_start=now - timedelta(days=1), period_end=now,
                                          status="processing", attempts=1)
                db.add(missing_model)
                db.flush()
                missing_model_id = missing_model.id
            try:
                process_run(missing_model_id)
                raise AssertionError("缺少模型连接时应失败")
            except Exception as exc:
                assert "配置聊天模型" in str(exc)
            with SessionLocal() as db:
                failed_row = db.get(DigestRun, missing_model_id)
                assert failed_row.status == "failed" and failed_row.note_id is None
                assert db.scalar(select(Note.id).where(Note.user_id == ids[1], Note.title.like("日报｜%"))) is None
            with SessionLocal.begin() as db:
                empty = DigestRun(user_id=ids[0], kind="daily", slot_key="empty-" + suffix,
                                  scheduled_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
                                  period_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
                                  period_end=datetime(2020, 1, 2, tzinfo=timezone.utc), status="processing", attempts=1)
                db.add(empty)
                db.flush()
                empty_id = empty.id
            with patch("app.assistant.digests.chat_model", return_value=FakeModel()):
                process_run(empty_id)
            with SessionLocal() as db:
                empty_note = db.get(Note, db.get(DigestRun, empty_id).note_id)
                assert "没有可用于生成回顾的已保存笔记活动" in empty_note.body_md
            with SessionLocal.begin() as db:
                from app.core.models import DigestSettings
                row = db.get(DigestSettings, ids[0])
                row.daily_next_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            assert enqueue_due() == 1
            assert enqueue_due() == 0
            with SessionLocal() as db:
                assert db.scalar(select(DigestRun).where(DigestRun.user_id == ids[0], DigestRun.kind == "daily", DigestRun.status == "pending")) is not None
            later = call(alice, "POST", f"/v1/notes/{note['id']}/reminders", 201, json={"text": "随笔记删除后隐藏", "due_at": due})
            assert later["id"] in [item["id"] for item in call(alice, "GET", "/v1/reminders", 200)["items"]]
            call(alice, "DELETE", f"/v1/notes/{note['id']}?version={note['version']}", 204)
            assert [item["id"] for item in call(alice, "GET", "/v1/reminders", 200)["items"]] == [standalone["id"]]
            assert all(item.get("note_id") != note["id"] for item in call(alice, "GET", "/v1/workbench", 200)["items"])
            assert any(item["id"] == standalone["id"] for item in call(alice, "GET", "/v1/workbench", 200)["items"])
            # 永久删除路径：归档笔记被彻底清除后必须一并整理引用它的记录，否则
            # pkm_digest_runs.note_id / pkm_note_reminders.note_id 会指向不存在的笔记，
            # 也就是 check_integrity 的 digest_runs_invalid_note / reminders_invalid_note 非零。
            # 上面只验证了软删除（提醒隐藏但保留，以便恢复笔记时带回），这一步才验证物理清除。
            report_body = call(alice, "GET", f"/v1/notes/{report['note_id']}", 200)
            call(alice, "DELETE", f"/v1/notes/{report['note_id']}?version={report_body['version']}", 204)
            with SessionLocal() as db:
                # 挂在待清除笔记上的提醒行数（含此前已被取消、但行仍保留的那条）。
                linked_before = len(db.scalars(select(NoteReminder.id).where(
                    NoteReminder.user_id == ids[0], NoteReminder.note_id == uuid.UUID(note["id"]),
                )).all())
            assert linked_before >= 1
            call(alice, "DELETE", f"/v1/notes/archive/{note['id']}", 204)
            call(alice, "DELETE", f"/v1/notes/archive/{report['note_id']}", 204)
            with SessionLocal() as db:
                # 排期账本不能消失：记录还在，只是不再指向任何笔记。
                detached = db.get(DigestRun, run_id)
                assert detached is not None and detached.status == "ready" and detached.note_id is None
                assert detached.period_start is not None and detached.source_refs is not None
                # 依附于已消失笔记的提醒被物理清除，独立提醒不受影响。
                assert db.get(NoteReminder, uuid.UUID(later["id"])) is None
                for stale_note in (note["id"], report["note_id"]):
                    assert db.scalar(select(NoteReminder.id).where(NoteReminder.note_id == uuid.UUID(stale_note))) is None
                assert db.get(NoteReminder, uuid.UUID(standalone["id"])) is not None
                assert db.scalar(select(DigestRun.id).join(
                    Note, (Note.id == DigestRun.note_id) & (Note.user_id == DigestRun.user_id), isouter=True,
                ).where(
                    DigestRun.user_id == ids[0], DigestRun.note_id.is_not(None), Note.id.is_(None),
                ).limit(1)) is None
            # 清理动作要在审计里留下可解释的痕迹，否则事后无法回答「这条报告记录为什么丢了笔记」。
            # 软删除同样写 DELETE 审计，所以必须用 purged 标记区分出真正的物理清除那一条。
            def purge_details(note_id: str) -> dict:
                with SessionLocal() as db:
                    return db.scalar(select(AuditEvent.details).where(
                        AuditEvent.user_id == ids[0],
                        AuditEvent.action == AuditAction.DELETE,
                        AuditEvent.entity_type == AuditEntityType.NOTE,
                        AuditEvent.entity_id == uuid.UUID(note_id),
                        AuditEvent.details["purged"].astext == "true",
                    ))
            assert purge_details(report["note_id"])["digest_runs_detached"] == 1
            assert purge_details(note["id"])["reminders_deleted"] == linked_before
            listed = [item for item in call(alice, "GET", "/v1/digests?kind=daily&limit=100", 200)["items"] if item["id"] == str(run_id)]
            assert len(listed) == 1 and listed[0]["note_id"] is None
            assert not listed[0]["note_active"] and not listed[0]["note_archived"]
            assert all(item["id"] != later["id"] for item in call(alice, "GET", "/v1/reminders?status=all", 200)["items"])
            print("日报、来源标题链接（内部编号不外泄）、可编辑报告、提醒持久化、双账号隔离和永久删除后的引用清理通过")
    finally:
        if ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, ids)


if __name__ == "__main__":
    main()
