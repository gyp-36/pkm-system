"""Verify the local Agent trace recorder without making model-provider calls."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.assistant.tracing as tracing
from app.core.db import SessionLocal
from app.core.models import Account, AssistantTrace
from app.main import app
from app.ops.maintenance import purge_accounts


def verify_environment_gate() -> None:
    prior_env = os.environ.get("APP_ENV")
    prior_enabled = os.environ.get("ASSISTANT_TRACE_VIEW_ENABLED")
    try:
        os.environ["APP_ENV"] = "development"
        os.environ["ASSISTANT_TRACE_VIEW_ENABLED"] = "true"
        assert tracing.trace_view_enabled()
        tracing.require_trace_view()
        os.environ["APP_ENV"] = "production"
        assert not tracing.trace_view_enabled()
        try:
            tracing.require_trace_view()
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("production trace endpoints must be disabled")
    finally:
        if prior_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = prior_env
        if prior_enabled is None:
            os.environ.pop("ASSISTANT_TRACE_VIEW_ENABLED", None)
        else:
            os.environ["ASSISTANT_TRACE_VIEW_ENABLED"] = prior_enabled


def verify_redacted_persistence_and_retention() -> None:
    os.environ["APP_ENV"] = "development"
    os.environ["ASSISTANT_TRACE_VIEW_ENABLED"] = "true"
    with SessionLocal() as db:
        user_id = db.scalar(select(Account.id).limit(1)) or uuid.uuid4()
    trace = tracing.TraceRecorder("verify", user_id, "local-model")
    assert trace.active
    callbacks = trace.callback_handler()
    model_run = uuid.uuid4()
    callbacks.on_chat_model_start({}, [], run_id=model_run)
    callbacks.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(
        content="MODEL_OUTPUT_SECRET",
        tool_calls=[{"name": "search_personal_notes", "args": {"question": "USER_QUESTION_SECRET"}}],
        usage_metadata={"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
    ))]]), run_id=model_run)
    tool_run = uuid.uuid4()
    callbacks.on_tool_start({"name": "search_personal_notes"}, json.dumps({"question": "USER_QUESTION_SECRET"}), run_id=tool_run)
    callbacks.on_tool_end("PRIVATE_NOTE_BODY_SECRET", run_id=tool_run)
    trace.record_evidence(SimpleNamespace(
        search_calls=1,
        read_calls=0,
        items={"S1": {"quote": "PRIVATE_NOTE_BODY_SECRET"}},
        semantic_status="ready",
    ))
    message_id = uuid.uuid4()
    trace.set_assistant_message(message_id)
    trace.finish("success")
    expired_id = uuid.uuid4()
    try:
        with SessionLocal() as db:
            stored = db.get(AssistantTrace, trace.id)
            assert stored is not None and stored.status == "success"
            serialized = json.dumps(stored.steps, ensure_ascii=False)
            for secret in ("MODEL_OUTPUT_SECRET", "USER_QUESTION_SECRET", "PRIVATE_NOTE_BODY_SECRET"):
                assert secret not in serialized
            assert "search_personal_notes" in serialized and "input_tokens" in serialized
            tool_step = next(step for step in stored.steps if step["kind"] == "tool")
            assert tool_step["status"] == "success" and tool_step["duration_ms"] is not None
            assert tool_step["summary"]["argument_fields"] == ["question"]
            db.add(AssistantTrace(
                id=expired_id,
                user_id=user_id,
                entrypoint="verify",
                status="success",
                started_at=datetime.now(timezone.utc) - timedelta(days=31),
                steps=[],
            ))
            db.commit()
        assert tracing.cleanup_expired_traces() >= 1
        with SessionLocal() as db:
            assert db.get(AssistantTrace, expired_id) is None
        verify_developer_routes(trace.id, message_id)
    finally:
        with SessionLocal() as db:
            for item_id in (trace.id, expired_id):
                item = db.get(AssistantTrace, item_id)
                if item is not None:
                    db.delete(item)
                    db.commit()


def verify_developer_routes(trace_id: uuid.UUID, message_id: uuid.UUID) -> None:
    account_ids: list[uuid.UUID] = []
    suffix = uuid.uuid4().hex[:12]
    try:
        with TestClient(app) as client:
            response = client.post("/v1/auth/register", json={"email": f"trace-{suffix}@example.com", "password": "TestPassword123!"})
            assert response.status_code == 201, response.text
            account_ids.append(uuid.UUID(response.json()["id"]))
            assert client.get("/v1/dev/assistant-traces/enabled").json() == {"enabled": True}
            page = client.get("/v1/dev/assistant-traces", params={"entrypoint": "verify", "status": "success", "limit": 10})
            assert page.status_code == 200 and any(item["id"] == str(trace_id) for item in page.json()["items"])
            assert client.get(f"/v1/dev/assistant-traces/{trace_id}").status_code == 200
            by_message = client.get(f"/v1/dev/assistant-traces/by-message/{message_id}")
            assert by_message.status_code == 200 and by_message.json()["id"] == str(trace_id)
            os.environ["APP_ENV"] = "production"
            assert client.get("/v1/dev/assistant-traces/enabled").json() == {"enabled": False}
            assert client.get("/v1/dev/assistant-traces").status_code == 404
            os.environ["APP_ENV"] = "development"
    finally:
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


def verify_storage_failure_is_nonfatal() -> None:
    prior_env = os.environ.get("APP_ENV")
    prior_enabled = os.environ.get("ASSISTANT_TRACE_VIEW_ENABLED")
    session_factory = tracing.SessionLocal

    class BrokenSession:
        def __enter__(self):
            raise RuntimeError("database is unavailable")

        def __exit__(self, *_args):
            return False

    try:
        os.environ["APP_ENV"] = "development"
        os.environ["ASSISTANT_TRACE_VIEW_ENABLED"] = "true"
        tracing.SessionLocal = lambda: BrokenSession()
        trace = tracing.TraceRecorder("verify", uuid.uuid4(), None)
        assert not trace.active
        trace.add_step("model", "模型调用")
        trace.finish("error", "RuntimeError")
    finally:
        tracing.SessionLocal = session_factory
        if prior_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = prior_env
        if prior_enabled is None:
            os.environ.pop("ASSISTANT_TRACE_VIEW_ENABLED", None)
        else:
            os.environ["ASSISTANT_TRACE_VIEW_ENABLED"] = prior_enabled


def main() -> None:
    verify_environment_gate()
    verify_redacted_persistence_and_retention()
    verify_storage_failure_is_nonfatal()
    print("assistant trace verification passed")


if __name__ == "__main__":
    main()
