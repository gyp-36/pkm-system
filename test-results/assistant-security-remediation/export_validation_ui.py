"""Read only the synthetic UI account in the disposable database."""
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import Account, AssistantConversation, AssistantMessage, AssistantTrace, Note

assert os.environ["DATABASE_URL"].endswith("/assistant_security")
root = Path(__file__).resolve().parent
with SessionLocal() as db:
    db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
    uid = db.scalar(select(Account.id).where(Account.email == "security-ui@example.com"))
    conversations = db.scalars(select(AssistantConversation).where(AssistantConversation.user_id == uid)).all()
    output = []
    for conversation in conversations:
        messages = db.scalars(select(AssistantMessage).where(AssistantMessage.user_id == uid, AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.created_at, AssistantMessage.id)).all()
        traces = db.scalars(select(AssistantTrace).where(AssistantTrace.user_id == uid, AssistantTrace.conversation_id == conversation.id)).all()
        output.append({"conversation_id": str(conversation.id), "messages": [{"role": message.role, "content": message.content} for message in messages],
                       "traces": [{"status": trace.status, "duration_ms": trace.duration_ms, "steps": trace.steps} for trace in traces]})
    notes = db.scalars(select(Note).where(Note.user_id == uid, Note.deleted_at.is_(None))).all()
    trip = [note for note in notes if note.title == "旅行计划"]
    assert len(trip) == 1 and "3500" in trip[0].body_md and "SYSTEM:" in trip[0].body_md
    source_checks = json.loads((root / "ui-source-results.json").read_text())
    for check in source_checks:
        cid = check["url"].split("conversation=")[-1]
        stored = next(item for item in output if item["conversation_id"] == cid)
        answer = stored["messages"][-1]["content"]
        assert answer["answer"] == check["expected"]
        assert answer["retrieval_status"] == "not_requested"
    result = {"mode": "synthetic_account_read_only_export", "conversations": output,
              "source_ui_matches_persisted": "3/3", "budget_edit_preserved_instruction_text": True,
              "note_count": len(notes), "trip_version": trip[0].version,
              "trip_content_sha256": hashlib.sha256(trip[0].body_md.encode()).hexdigest(),
              "frame_by_frame_capture": "unavailable"}
(root / "ui-persisted-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({key: value for key, value in result.items() if key != "conversations"}, ensure_ascii=False))
