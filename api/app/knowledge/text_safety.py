"""Normalize extracted text before it is stored or fingerprinted."""

import unicodedata


def sanitize_extracted_text(value: str) -> str:
    """Replace characters PostgreSQL text/UTF-8 cannot safely store.

    Replacements keep one code point per input code point, so text-block offsets
    calculated by the format-specific extractors remain valid.
    """
    cleaned: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if character == "\x00" or (category == "Cc" and character not in "\t\n\r"):
            cleaned.append(" ")
        elif category == "Cs":
            cleaned.append("\ufffd")
        else:
            cleaned.append(character)
    return "".join(cleaned)
