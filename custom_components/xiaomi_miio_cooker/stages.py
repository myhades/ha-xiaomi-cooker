"""Official rice curve phases: CMC301 10610/10871 and normal3 10904/11030."""

import re

from .models import CookerStageData

RICE_PHASES = (
    "quick_preheat",
    "water_absorption",
    "boiling",
    "gelatinization",
    "simmering",
)


def history_payload(value) -> tuple[int, ...]:
    """Skip the two prefix bytes, preserving phase separators for interpretation."""
    if (
        not isinstance(value, str)
        or len(value) < 6
        or len(value) % 2
        or not re.fullmatch(r"[0-9a-fA-F]+", value)
    ):
        return ()
    return tuple(bytes.fromhex(value)[2:])


def rice_history_stage(payload: tuple[int, ...]) -> CookerStageData | None:
    """No fabricated initial phase for empty/marker-only or out-of-range history."""
    if not any(value != 0xAA for value in payload):
        return None
    index = payload.count(0xAA)
    if index >= len(RICE_PHASES):
        return None
    return CookerStageData(
        state=index,
        rice_id=None,
        taste=None,
        taste_phase=None,
        name=None,
        description=None,
        phase=RICE_PHASES[index],
    )
