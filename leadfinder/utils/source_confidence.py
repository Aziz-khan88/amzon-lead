from __future__ import annotations


def clamp_confidence(value: float | int | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        labels = {
            "very high": 0.95,
            "high": 0.85,
            "medium": 0.55,
            "moderate": 0.55,
            "low": 0.25,
            "very low": 0.1,
            "unclear": 0.2,
        }
        if normalized in labels:
            return labels[normalized]
        try:
            value = float(normalized)
        except ValueError:
            return 0.0
    return max(0.0, min(1.0, float(value)))


def merge_confidence(*values: float | None) -> float:
    present = [clamp_confidence(v) for v in values if v is not None]
    if not present:
        return 0.0
    return round(sum(present) / len(present), 2)
