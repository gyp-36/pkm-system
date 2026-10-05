"""Load model instructions from the centralized prompt directory."""

from __future__ import annotations

import re
from pathlib import Path


_PROMPT_DIRECTORY = Path(__file__).resolve().parent
_PROMPT_NAME = re.compile(r"[a-z][a-z0-9_]*\.txt\Z")
_PLACEHOLDER = re.compile(r"\[\[([^\]]+)\]\]")
_PLACEHOLDER_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")


def load_prompt(name: str, **values: str) -> str:
    """Load a UTF-8 prompt and replace its explicit ``[[name]]`` tokens."""
    if not _PROMPT_NAME.fullmatch(name):
        raise ValueError(f"invalid prompt name: {name!r}")

    path = _PROMPT_DIRECTORY / name
    template = path.read_text(encoding="utf-8").removesuffix("\n")
    placeholders = set(_PLACEHOLDER.findall(template))
    invalid = {item for item in placeholders if not _PLACEHOLDER_NAME.fullmatch(item)}
    if invalid:
        raise ValueError(f"invalid placeholders in prompt {name!r}: {', '.join(sorted(invalid))}")
    supplied = set(values)
    missing = placeholders - supplied
    unexpected = supplied - placeholders
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing values: {', '.join(sorted(missing))}")
        if unexpected:
            details.append(f"unused values: {', '.join(sorted(unexpected))}")
        raise ValueError(f"invalid values for prompt {name!r}: {'; '.join(details)}")

    for key, value in values.items():
        if not isinstance(value, str):
            raise TypeError(f"prompt value {key!r} must be a string")
        template = template.replace(f"[[{key}]]", value)

    return template
