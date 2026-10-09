"""Current user-facing projections for stored, replayed and generated data.

Old rows are retained. Unregistered server extensions never leave the process;
document strings remain strings even when they contain JSON or code.
"""
from app.assistant.data_contract import validate_shape
from app.assistant.visibility import project_text


CITATION = {"citation_id": str, "note_id": str, "title": str}
FIELDS = {"title": str, "body_md": str}
RECEIPT = {"action": str, "title": str}
SELECTION = {"operation_id": str, "kind": str, "candidates": [{"index": int, "title": str, "notebook": (str, type(None))}]}
CONFIRMATION = {"operation_id": str, "kind": str, "changes": [{"title": str, "before": FIELDS, "after": FIELDS}]}
INPUT = {"operation_id": str, "kind": str, "action": str, "missing": [str]}


def safe_shape(value, schema, fallback):
    try:
        return validate_shape(value, schema, project=True)
    except KeyError:
        return fallback


def public_content(content, *, user=False, literals=()):
    content = content if isinstance(content, dict) else {}
    if user:
        return {"text": content.get("text", "") if isinstance(content.get("text"), str) else ""}
    if "answer" not in content and isinstance(content.get("items"), list):
        items = safe_shape(content["items"], [{"title": str, "snippet": str}], [])
        return {"items": [{"title": item.get("title", "笔记"), "snippet": project_text(item.get("snippet", ""), literals=literals)} for item in items]}
    citations = safe_shape(content.get("citations", []), [CITATION], [])
    citations = [c for c in citations if set(c) == set(CITATION)]
    identities = [c["note_id"] for c in citations]
    answer = project_text(content.get("answer", ""), identities=identities, literals=literals)
    pending = content.get("pending_operation")
    if isinstance(pending, dict) and pending.get("kind") in ("selection", "confirmation", "input"):
        kind = pending["kind"]
        pending = safe_shape(pending, {"selection": SELECTION, "confirmation": CONFIRMATION, "input": INPUT}[kind], None)
        # A malformed preview must not become an actionable confirmation.
        required = {"operation_id", "kind", *({"selection": ["candidates"], "confirmation": ["changes"], "input": ["action", "missing"]}[kind])}
        if pending is not None and not required.issubset(pending):
            pending = None
        if pending is not None and kind == "input" and (pending["action"] not in {"create", "update"} or any(f not in {"target_title", "body_md", "title"} for f in pending["missing"])):
            pending = None
    else:
        pending = None
    return {"answer": answer, "citations": citations,
            "semantic_status": content.get("semantic_status") if content.get("semantic_status") in ("ready", "unavailable", "not_requested") else "not_requested",
            "answer_source": content.get("answer_source") if content.get("answer_source") in ("knowledge_base", "mixed", "model_knowledge", "unknown") else "unknown",
            "retrieval_status": content.get("retrieval_status") if content.get("retrieval_status") in ("not_requested", "no_results", "retrieved", "error", "unknown") else "unknown",
            "pending_operation": pending,
            "operation_receipts": [r for r in safe_shape(content.get("operation_receipts", []), [RECEIPT], []) if set(r) == set(RECEIPT) and r["action"] in {"created", "updated", "already_exists"}]}


def public_conversation(response, *, literals=()):
    result = safe_shape(response, {"id": str, "title": str, "created_at": str, "updated_at": str}, {})
    messages = []
    literal_data = list(literals)
    for item in response.get("messages", []):
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        message = safe_shape(item, {"id": str, "role": str, "created_at": str}, {})
        if len(message) != 3:
            continue
        raw = item.get("content")
        if item["role"] == "user" and isinstance(raw, dict) and isinstance(raw.get("text"), str):
            literal_data.append(raw["text"])
        message["content"] = public_content(raw, user=item["role"] == "user", literals=literal_data)
        messages.append(message)
    result["messages"] = messages
    return result
