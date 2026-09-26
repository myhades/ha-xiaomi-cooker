"""Shared recipe draft and duration choices; wire layouts remain model-specific."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeOptions:
    """Parameters for the next start, not device readback."""

    duration: int
    auto_keep_warm: bool
    taste: int
    finish_in: int = 0


@dataclass(frozen=True)
class ScheduledRecipe:
    """A relative normal3 request; resolve its clock time just before sending."""

    profile: str
    finish_in: int
    time_zone: str


def duration_choices(minimum: int, maximum: int, default: int) -> list[int]:
    """Keep template endpoints/default, with five or ten minute grid points."""
    if not 1 <= minimum <= default <= maximum <= 1440:
        raise ValueError("Invalid recipe duration range")
    step = 5 if maximum - minimum <= 60 else 10
    first = ((minimum + step - 1) // step) * step
    return sorted({minimum, maximum, default, *range(first, maximum + 1, step)})
