"""Cooking profile helpers for Xiaomi Cooker."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .const import (
    MODEL_CMC301,
    MODEL_NORMAL2,
    MODEL_NORMAL3,
    MODEL_NORMAL4,
    MODEL_NORMAL5,
    MODEL_PRESSURE1,
    MODEL_PRESSURE2,
)

PROFILE_DATA_FILE = "cooker_profiles.json"
PROFILE_KEY_PATTERN = re.compile(r"[^a-z0-9]+")
COMMON_MENU_ID_TO_KEY: dict[int, str] = {
    1: "jingzhu",
    2: "kuaizhu",
    3: "zhuzhou",
    4: "baowen",
    256: "cake",
    257: "yoghurt",
    258: "refan",
    259: "cooking",
}
COMMON_MENU_OTHER = "other"
COMMON_MENU_OPTIONS = (*COMMON_MENU_ID_TO_KEY.values(), COMMON_MENU_OTHER)

PROFILE_GROUP_MODELS: dict[str, tuple[str, ...]] = {
    "MODEL_PRESSURE": (MODEL_PRESSURE1, MODEL_PRESSURE2),
    "MODEL_NORMAL_GROUP1": (MODEL_NORMAL2, MODEL_NORMAL5),
    "MODEL_NORMAL_GROUP2": (MODEL_NORMAL3, MODEL_NORMAL4),
}

MODEL_TO_PROFILE_GROUP = {
    model: group for group, models in PROFILE_GROUP_MODELS.items() for model in models
}


@dataclass(slots=True, frozen=True)
class CookingProfile:
    """A selectable cooking profile."""

    key: str
    title: str
    description: str
    profile: str


def _normalize_profile_key(title: str) -> str:
    """Convert a profile title into a stable option key."""
    normalized = PROFILE_KEY_PATTERN.sub("_", title.strip().lower()).strip("_")
    return normalized or "profile"


@lru_cache(maxsize=1)
def _load_profiles_by_group() -> dict[str, tuple[CookingProfile, ...]]:
    """Load bundled profile data."""
    raw_data = json.loads(
        Path(__file__).with_name(PROFILE_DATA_FILE).read_text(encoding="utf-8")
    )
    return {
        group: tuple(
            CookingProfile(
                key=_normalize_profile_key(item["title"]),
                title=item["title"],
                description=item["description"],
                profile=item["profile"],
            )
            for item in raw_data[group]
        )
        for group in PROFILE_GROUP_MODELS
    }


def get_profiles_for_model(model: str | None) -> tuple[CookingProfile, ...]:
    """Return supported cooking profiles for a given cooker model."""
    if model == MODEL_CMC301:
        return _load_cmc301_profiles()
    if model == MODEL_NORMAL3:
        return _load_normal3_profiles()
    if model is None:
        return ()

    group = MODEL_TO_PROFILE_GROUP.get(model)
    if group is None:
        return ()

    return _load_profiles_by_group().get(group, ())


def get_menu_key(menu_id: int | None, model: str | None = None) -> str | None:
    """Return the stable enum key for a known common menu ID."""
    if menu_id is None:
        return None
    if model == MODEL_NORMAL3:
        for recipe in _load_normal3_profiles():
            if int(recipe.profile[:4], 16) == menu_id:
                return recipe.key

    return COMMON_MENU_ID_TO_KEY.get(menu_id)


@lru_cache(maxsize=1)
def _load_normal3_profiles() -> tuple[CookingProfile, ...]:
    from .normal3_profile import decode_profile

    raw = json.loads(
        Path(__file__).with_name("normal3_recipes.json").read_text(encoding="utf-8")
    )
    profiles = []
    for item in raw["recipes"]:
        decode_profile(item["profile"])
        profiles.append(
            CookingProfile(item["key"], item["name"], item["name"], item["profile"])
        )
    return tuple(profiles)


@lru_cache(maxsize=1)
def _load_cmc301_profiles() -> tuple[CookingProfile, ...]:
    from .cmc301_profile import decode_profile

    raw = json.loads(
        Path(__file__).with_name("cmc301_recipes.json").read_text(encoding="utf-8")
    )
    profiles = []
    for item in raw["recipes"]:
        decode_profile(item["profile"])
        profiles.append(
            CookingProfile(item["key"], item["name"], item["name"], item["profile"])
        )
    return tuple(profiles)


def get_cmc301_menu_key(menu_id: int) -> str:
    for recipe in _load_cmc301_profiles():
        if int(recipe.profile[6:14], 16) == menu_id:
            return recipe.key
    return COMMON_MENU_OTHER
