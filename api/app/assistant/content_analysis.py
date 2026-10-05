"""Shared, direction-guided analysis for saved notes and captured web content."""

import json
import re

from langchain.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.prompts import load_prompt


class ContentAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    key_points: list[str] = Field(min_length=1, max_length=8)
    action_suggestions: list[str] = Field(min_length=1, max_length=8)


def analyze_content(model, content: str, *, source_label: str) -> ContentAnalysis:
    """Analyze supplied content in a controlled direction and validate the model result."""
    instruction = load_prompt("content_analysis_system.txt", source_label=source_label)
    answer = model.invoke([
        SystemMessage(content=instruction),
        HumanMessage(content=json.dumps({"content": content}, ensure_ascii=False)),
    ])
    raw = answer.content if isinstance(answer.content, str) else ""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    return ContentAnalysis.model_validate(json.loads(cleaned))


def generate_link_note_content(
    model,
    *,
    source_title: str,
    source_url: str,
    content: str,
    instructions: str = "",
) -> str:
    """Generate a Markdown proposal from parsed link content without persisting it."""
    answer = model.invoke([
        SystemMessage(content=load_prompt("link_note_draft_system.txt")),
        HumanMessage(content=json.dumps({
            "user_instructions": instructions[:1000],
            "source_title": source_title,
            "source_url": source_url,
            "parsed_content": content[:30_000],
        }, ensure_ascii=False)),
    ])
    generated = answer.content if isinstance(answer.content, str) else ""
    return generated[:100_000].strip()
