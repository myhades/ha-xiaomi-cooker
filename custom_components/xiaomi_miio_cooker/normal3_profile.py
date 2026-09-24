"""normal3 header edits from official plugin 1002206 modules 10445/11027."""

import re
from binascii import crc_hqx

from .exceptions import RecipeValidationError
from .recipe_options import RecipeOptions


def decode_profile(profile: str) -> bytes:
    if not isinstance(profile, str) or not re.fullmatch(r"[0-9a-fA-F]{242}", profile):
        raise RecipeValidationError(
            "invalid_recipe",
            "normal3 recipes must contain exactly 121 hexadecimal bytes",
        )
    data = bytes.fromhex(profile)
    if crc_hqx(data[:-2], 0) != int.from_bytes(data[-2:], "big"):
        raise RecipeValidationError(
            "invalid_recipe",
            "Invalid normal3 recipe checksum; obtain a trusted template",
        )
    return data


def minutes(data: bytes, offset: int) -> int:
    return data[offset] * 60 + data[offset + 1]


def duration_range(profile: str) -> tuple[int, int]:
    data = decode_profile(profile)
    duration = minutes(data, 3)
    # Fine rice reuses byte 7 for taste. Fixed recipes commonly have zero bounds.
    if int.from_bytes(data[:2], "big") == 1:
        return duration, duration
    minimum, maximum = minutes(data, 7), minutes(data, 5)
    return (minimum, maximum) if maximum > minimum else (duration, duration)


def default_options(profile: str) -> RecipeOptions:
    data = decode_profile(profile)
    return RecipeOptions(
        minutes(data, 3),
        bool(data[10] & 0x80),
        data[7] if int.from_bytes(data[:2], "big") == 1 else 0,
    )


def supports_option(profile: str, key: str) -> bool:
    data = decode_profile(profile)
    return {
        "duration": True,
        "auto_keep_warm": bool(data[2] & 0x20),
        "taste": int.from_bytes(data[:2], "big") == 1,
    }.get(key, False)


def encode_profile(profile: str, options: RecipeOptions) -> str:
    """Preserve program bytes and legacy defaults; do not invent scheduling."""
    original = decode_profile(profile)
    minimum, maximum = duration_range(profile)
    defaults = default_options(profile)
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
    if options.auto_keep_warm != defaults.auto_keep_warm and not supports_option(
        profile, "auto_keep_warm"
    ):
        raise RecipeValidationError(
            "keep_warm_unsupported", "This recipe does not support automatic keep warm"
        )
    if type(options.taste) is not int or options.taste not in (0, 1, 2):
        raise RecipeValidationError("invalid_taste", "Taste must be 0, 1 or 2")
    if options.taste != defaults.taste and not supports_option(profile, "taste"):
        raise RecipeValidationError(
            "taste_unsupported", "Only fine rice supports taste adjustment"
        )
    if type(options.finish_in) is not int or options.finish_in != 0:
        raise RecipeValidationError(
            "schedule_unsupported",
            "Scheduled recipe preparation is not supported for normal3",
        )
    if options == defaults:
        return profile
    data = bytearray(original)
    data[3:5] = bytes(divmod(options.duration, 60))
    data[10] = (data[10] & 0x7F) | (0x80 if options.auto_keep_warm else 0)
    if supports_option(profile, "taste"):
        data[7] = options.taste
    data[-2:] = crc_hqx(data[:-2], 0).to_bytes(2, "big")
    return data.hex()
