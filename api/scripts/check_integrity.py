"""Report orphan and cross-account links without modifying business data."""

import json

from app.db import engine
from app.integrity import integrity_counts


def main() -> None:
    with engine.connect() as connection:
        counts = integrity_counts(connection)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    if any(counts.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
