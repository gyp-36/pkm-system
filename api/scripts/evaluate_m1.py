"""Run the PRD's fixed 20-question retrieval evaluation with disposable data."""

import json
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

import httpx
from app.core.db import SessionLocal
from app.ops.maintenance import purge_accounts


CASES = json.loads(Path(__file__).with_name("evaluation_cases.json").read_text())
BASE = os.getenv("M1_TEST_API_URL", "http://api:8000")


def main() -> None:
    account_id = None
    with httpx.Client(base_url=BASE, timeout=180) as client:
        try:
            email = f"eval-{uuid.uuid4().hex[:12]}@example.com"
            response = client.post("/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
            response.raise_for_status()
            account_id = uuid.UUID(response.json()["id"])
            ids = {}
            for item in CASES["notes"]:
                response = client.post("/v1/notes", json={"title": item["title"], "body_md": item["body_md"]})
                response.raise_for_status()
                ids[item["key"]] = response.json()["id"]

            for _ in range(90):
                statuses = [client.get(f"/v1/notes/{note_id}").json()["index_status"] for note_id in ids.values()]
                if all(status == "ready" for status in statuses):
                    break
                time.sleep(2)
            assert all(status == "ready" for status in statuses), statuses

            totals = defaultdict(lambda: {"questions": 0, "keyword": 0, "hybrid": 0, "empty_hybrid": 0})
            report = []
            bad_offsets = []
            for case in CASES["questions"]:
                row = {"group": case["group"], "q": case["q"], "targets": case["targets"]}
                target_ids = {ids[key] for key in case["targets"]}
                for mode in ("keyword", "hybrid"):
                    response = client.get("/v1/search", params={"q": case["q"], "mode": mode, "limit": 20})
                    response.raise_for_status()
                    payload = response.json()
                    assert payload["semantic_status"] == ("ready" if mode == "hybrid" else "not_requested"), payload
                    hits = payload["items"]
                    found = {item["note_id"] for item in hits}
                    row[mode] = target_ids.issubset(found) if target_ids else not hits
                    row[f"{mode}_count"] = len(hits)
                    for item in hits:
                        note = client.get(f"/v1/notes/{item['note_id']}").json()
                        source = note["title"] if item["source_field"] == "title" else note["body_md"]
                        if note["version"] != item["version"] or source[item["start_offset"] : item["end_offset"]] != item["snippet"]:
                            bad_offsets.append({"q": case["q"], "note_id": item["note_id"], "mode": mode})
                totals[case["group"]]["questions"] += 1
                totals[case["group"]]["keyword"] += int(row["keyword"])
                totals[case["group"]]["hybrid"] += int(row["hybrid"])
                if case["group"] == "no_answer":
                    totals[case["group"]]["empty_hybrid"] += int(row["hybrid"])
                report.append(row)
            print(json.dumps({"summary": totals, "bad_offsets": bad_offsets, "questions": report}, ensure_ascii=False, indent=2))
        finally:
            if account_id:
                with SessionLocal.begin() as db:
                    purge_accounts(db, [account_id])


if __name__ == "__main__":
    main()
