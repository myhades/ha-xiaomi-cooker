"""CMC301 recipe codec. Only documented header fields are edited."""

from __future__ import annotations

import re
from binascii import crc_hqx

from .exceptions import RecipeValidationError
from .recipe_options import RecipeOptions as RecipeOptions


def decode_profile(profile: str) -> bytes:
    """Reject malformed or corrupted payloads before any device call."""
    if not isinstance(profile, str) or not re.fullmatch(r"[0-9a-fA-F]{352}", profile):
        raise RecipeValidationError(
            "invalid_recipe",
            "CMC301 recipes must contain exactly 176 hexadecimal bytes",
        )
    data = bytes.fromhex(profile)
    if crc_hqx(data[:-2], 0) != int.from_bytes(data[-2:], "big"):
        raise RecipeValidationError("invalid_recipe", "Invalid CMC301 recipe checksum")
    return data


def minutes(data: bytes, offset: int) -> int:
    """Decode a two-byte hour/minute field."""
    return data[offset] * 60 + data[offset + 1]


def default_options(profile: str) -> RecipeOptions:
    data = decode_profile(profile)
    return RecipeOptions(minutes(data, 8), bool(data[15] & 0x80), data[19])


def duration_range(profile: str) -> tuple[int, int]:
    data = decode_profile(profile)
    return minutes(data, 12), minutes(data, 10)


def supports_option(profile: str, key: str) -> bool:
    data = decode_profile(profile)
    return {
        "duration": True,
        "finish_in": bool(data[7] & 0x40),
        "auto_keep_warm": bool(data[7] & 0x20),
        "taste": int.from_bytes(data[3:7], "big") == 2,
    }.get(key, False)


def encode_profile(profile: str, options: RecipeOptions, *, panel: bool = False) -> str:
    """Apply menu-specific constraints and preserve the heating program verbatim."""
    original = decode_profile(profile)
    data = bytearray(original)
    menu_id = int.from_bytes(data[3:7], "big")
    minimum, maximum = minutes(data, 12), minutes(data, 10)
    if type(options.duration) is not int or not minimum <= options.duration <= maximum:
        raise RecipeValidationError(
            "duration_out_of_range",
            f"Cooking duration must be {minimum}-{maximum} minutes",
            minimum=minimum,
            maximum=maximum,
        )
    if type(options.auto_keep_warm) is not bool:
        raise RecipeValidationError(
            "invalid_keep_warm", "Auto keep warm must be a boolean"
        )
    if options.auto_keep_warm and not data[7] & 0x20:
        raise RecipeValidationError(
            "keep_warm_unsupported", "This recipe does not support automatic keep warm"
        )
    if type(options.taste) is not int or options.taste not in (0, 1, 2):
        raise RecipeValidationError("invalid_taste", "Taste must be 0, 1 or 2")
    if menu_id != 2 and options.taste != data[19]:
        raise RecipeValidationError(
            "taste_unsupported", "Only fine rice supports taste adjustment"
        )
    if type(options.finish_in) is not int or not 0 <= options.finish_in <= 1439:
        raise RecipeValidationError(
            "invalid_finish_in", "Finish in must be 0-1439 minutes"
        )
    if options.finish_in:
        if not data[7] & 0x40:
            raise RecipeValidationError(
                "schedule_unsupported", "This recipe does not support scheduled cooking"
            )
        # The official quick-rice page reserves an additional 12 minutes.
        minimum_finish = options.duration + (12 if menu_id == 1 else 0)
        if options.finish_in <= minimum_finish:
            raise RecipeValidationError(
                "finish_too_soon",
                f"Finish in must exceed {minimum_finish} minutes, or be 0",
                minimum=minimum_finish,
            )
    data[8:10] = bytes(divmod(options.duration, 60))
    hour, minute = divmod(options.finish_in, 60)
    data[14] = hour | (0x80 if options.finish_in else 0)
    data[15] = minute | (0x80 if options.auto_keep_warm else 0)
    data[19] = options.taste
    if panel:
        if options.finish_in:
            raise RecipeValidationError(
                "clear_schedule", "A panel recipe cannot include a scheduled start"
            )
        data[2] = 4
    data[-2:] = crc_hqx(data[:-2], 0).to_bytes(2, "big")
    return data.hex()


def validate_bundled_profile(profile: str) -> None:
    """Allow only known heating programs, with valid supported parameter edits."""
    from .const import MODEL_CMC301
    from .profiles import get_profiles_for_model

    data = decode_profile(profile)
    menu_id = int.from_bytes(data[3:7], "big")
    for recipe in get_profiles_for_model(MODEL_CMC301):
        base = decode_profile(recipe.profile)
        if int.from_bytes(base[3:7], "big") != menu_id:
            continue
        options = RecipeOptions(
            minutes(data, 8),
            bool(data[15] & 0x80),
            data[19],
            (data[14] & 0x7F) * 60 + (data[15] & 0x7F) if data[14] & 0x80 else 0,
        )
        if profile.lower() == encode_profile(recipe.profile, options):
            return
        break
    raise RecipeValidationError(
        "untrusted_recipe",
        "CMC301 accepts only bundled recipes with supported parameter edits",
    )
