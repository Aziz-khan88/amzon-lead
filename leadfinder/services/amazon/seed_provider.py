from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


def read_seed_csv(path: str | Path) -> Iterable[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield {str(k).strip().lower(): (v or "").strip() for k, v in row.items()}
