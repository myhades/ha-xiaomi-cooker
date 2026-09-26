"""CMC301 protocol, settings and recipe encoding."""

from __future__ import annotations

import re
from binascii import crc_hqx
from time import monotonic

from miio import DeviceException

from .const import AUTO_KEEP_WARM_MINUTES
from .exceptions import CookerCommandError, RecipeValidationError
from .models import CookerData, CookerStatusData
from .recipe_options import RecipeOptions
from .stages import history_payload, rice_history_stage


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


PROPERTIES = {
    "status_code": (2, 1),
    "fault": (2, 2),
    "mode_code": (2, 3),
    "recipe_id": (2, 19),
    "duration": (2, 20),
    "remaining_seconds": (2, 21),
    "texture": (2, 26),
    "boiling": (2, 29),
    "recipe_type": (2, 30),
    "reset_flag": (2, 31),
    "remote_control": (7, 1),
}
STATES = {
    1: "idle",
    2: "running",
    3: "scheduled",
    4: "keep_warm",
    5: "error",
    6: "updating",
    7: "completed",
}
FAULTS = {0: "none", 5: "top_sensor", 6: "bottom_sensor", 7: "communication"}

MODES = {1: "quick_cook", 2: "fine_cook", 3: "cook_congee", 4: "keep_warm", 5: "custom"}


def parse_history(value) -> tuple[int, ...]:
    """Match the plugin: skip the first two bytes and AA stage separators."""
    return tuple(sample for sample in history_payload(value) if sample != 0xAA)


class Cmc301Backend:
    def __init__(self, device, metadata) -> None:
        self.device = device
        self.metadata = metadata
        self._history_at = None
        self._history = ()
        self._history_context = None
        self._history_stage = None
        self._panel_recipe_id = None

    def _read(self, mapping: dict) -> dict:
        values = {}
        items = list(mapping.items())
        for offset in range(0, len(items), 6):
            chunk = items[offset : offset + 6]
            params = [
                {"did": "miot", "siid": siid, "piid": piid} for _, (siid, piid) in chunk
            ]
            response = self.device.send("get_properties", params, retry_count=1)
            if not isinstance(response, list):
                raise DeviceException("Invalid MIoT property response")
            by_id = {
                (row.get("siid"), row.get("piid")): row
                for row in response
                if isinstance(row, dict)
            }
            for key, address in chunk:
                row = by_id.get(address, {})
                values[key] = row.get("value") if row.get("code") == 0 else None
        return values

    def _action(self, siid: int, aiid: int, inputs: list, *, retries: int = 0) -> dict:
        result = self.device.send(
            "action",
            {"did": "miot", "siid": siid, "aiid": aiid, "in": inputs},
            retry_count=retries,
        )
        if not isinstance(result, dict) or result.get("code") != 0:
            code = (
                result.get("code") if isinstance(result, dict) else "invalid response"
            )
            raise DeviceException(f"MIoT action {siid}.{aiid} failed ({code})")
        return result

    def _read_settings(self) -> bytearray:
        result = self._action(6, 2, [], retries=1)
        if not isinstance(result.get("out"), list):
            raise DeviceException("Invalid CMC301 settings response")
        value = next(
            (
                item.get("value")
                for item in result.get("out", [])
                if isinstance(item, dict) and item.get("piid") == 1
            ),
            None,
        )
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}", value):
            raise DeviceException("Invalid CMC301 settings response")
        return bytearray.fromhex(value)

    def fetch_data(self) -> CookerData:
        values = self._read(PROPERTIES)
        if type(values["status_code"]) is not int:
            raise DeviceException("CMC301 did not return its working status")
        if values["mode_code"] == 5 and type(values["recipe_id"]) is int:
            self._panel_recipe_id = values["recipe_id"]
        values["panel_recipe_id"] = self._panel_recipe_id
        try:
            settings = self._read_settings()
        except DeviceException:
            settings = None
        values.update(
            {
                "panel_auto_off": settings[0] == 0
                if settings is not None and settings[0] in (0, 1)
                else None,
                "display_timeout": settings[1] if settings is not None else None,
                "completion_notification": settings[2] == 0
                if settings is not None and settings[2] in (0, 1)
                else None,
                "all_modes_lit": settings[3] == 1
                if settings is not None and settings[3] in (0, 1)
                else None,
            }
        )
        now = monotonic()
        history_context = (values["status_code"], values["recipe_id"], values["fault"])
        # Official running page only shows these phases for the two rice menus.
        show_rice_stage = (
            values["status_code"] == 2
            and values["recipe_id"] in (1, 2)
            and values["fault"] == 0
        )
        # The device clears history on stop. At the beginning of a scheduled cook
        # history is empty, then appears without a change in status code 3.
        interval = (
            30
            if show_rice_stage
            or (values["status_code"] in (2, 3, 4) and not self._history)
            else 120
        )
        if (
            history_context != self._history_context
            or self._history_at is None
            or now - self._history_at >= interval
        ):
            self._history_context = history_context
            self._history_at = now
            try:
                payload = history_payload(self._read({"history": (2, 28)})["history"])
                self._history = tuple(value for value in payload if value != 0xAA)
                self._history_stage = rice_history_stage(payload)
            except DeviceException:
                self._history = ()
                self._history_stage = None
        values["history_samples"] = len(self._history)
        values["recorded_temperature"] = self._history[-1] if self._history else None
        values["stage_source"] = "temperature_history"
        stage = self._history_stage if show_rice_stage else None
        remaining = values["remaining_seconds"]
        warming = values["status_code"] == 4
        recipe_id = values["recipe_id"]
        warm_type = (
            ("manual" if recipe_id == 4 else "automatic")
            if warming and type(recipe_id) is int and recipe_id > 0
            else None
            if warming
            else "none"
        )
        values["keep_warm_type"] = warm_type
        values["time_direction"] = "elapsed" if warming else "remaining"
        values["cooking_finished"] = (
            values["fault"] == 0
            and type(recipe_id) is int
            and recipe_id > 0
            and recipe_id != 4
            and (values["status_code"] == 7 or warm_type == "automatic")
        )
        minutes_left = None
        if type(remaining) is int and remaining >= 0:
            if warming:
                # Official plugin 10202 distinguishes menu 4; 10187 specifies
                # a 24-hour limit for automatic keep-warm. Never use the rice
                # cooking duration as the automatic keep-warm countdown base.
                duration = (
                    AUTO_KEEP_WARM_MINUTES
                    if warm_type == "automatic"
                    else values["duration"]
                )
                if (
                    warm_type is not None
                    and type(duration) is int
                    and 0 < duration <= 1440
                    and remaining <= duration * 60
                ):
                    minutes_left = (duration * 60 - remaining) // 60
            else:
                minutes_left = (remaining + 59) // 60
        return CookerData(
            device_info=self.metadata,
            status=CookerStatusData(
                mode=MODES.get(values["mode_code"], "unknown"),
                status=STATES.get(values["status_code"], "unknown"),
                menu=values["recipe_id"],
                remaining=minutes_left,
                duration=values["duration"],
                favorite=None,
                stage=stage,
            ),
            settings=None,
            interaction_timeouts=None,
            temperature=None,
            properties=values,
        )

    def _require_idle(self) -> None:
        values = self._read(
            {key: PROPERTIES[key] for key in ("status_code", "fault", "remote_control")}
        )
        if values["remote_control"] is not True:
            raise CookerCommandError(
                "remote_denied", "Remote cooking is not permitted by the cooker"
            )
        if values["status_code"] not in (1, 7) or values["fault"] != 0:
            raise CookerCommandError(
                "cooker_busy", "Cooker must be idle and free of faults before starting"
            )

    def start(self, profile: str):
        validate_bundled_profile(profile)
        self._require_idle()
        self._history_at = None
        self._history = ()
        self._history_stage = None
        try:
            return self._action(2, 6, [{"piid": 27, "value": profile}])
        except DeviceException as err:
            raise CookerCommandError(
                "start_unconfirmed",
                "Start was not confirmed; check cooker status before retrying",
            ) from err

    def stop(self):
        # Stop remains accessible even when remote-control permission is false.
        return self._action(2, 2, [], retries=1)

    def set_panel_recipe(self, profile: str) -> None:
        validate_bundled_profile(profile)
        self._require_idle()
        panel_profile = encode_profile(profile, default_options(profile), panel=True)
        self._action(
            2,
            5,
            [
                {"piid": 27, "value": "info_" + panel_profile},
                {"piid": 32, "value": True},
            ],
        )
        # Saving switches the panel to custom mode; confirm the actual selection.
        values = self._read(
            {key: PROPERTIES[key] for key in ("mode_code", "recipe_id")}
        )
        expected = int(profile[6:14], 16)
        self._panel_recipe_id = (
            values["recipe_id"] if values["mode_code"] == 5 else None
        )
        if self._panel_recipe_id != expected:
            raise CookerCommandError(
                "write_unconfirmed", "Panel recipe was not confirmed"
            )

    def set_setting(self, key: str, value) -> None:
        fields = {
            "panel_auto_off": (0, True),
            "completion_notification": (2, True),
            "all_modes_lit": (3, False),
        }
        if key == "panel_sleep":
            if value != "off" and (type(value) is not int or not 2 <= value <= 10):
                raise ValueError("Panel sleep must be off or 2-10 minutes")
            updates = {0: 1} if value == "off" else {0: 0, 1: value}
        elif key == "display_timeout":
            if type(value) is not int or not 2 <= value <= 10:
                raise ValueError("Display timeout must be 2-10 minutes")
            updates = {1: value}
        elif key in fields and type(value) is bool:
            index, inverted = fields[key]
            updates = {index: int(not value if inverted else value)}
        else:
            raise ValueError("Unsupported cooker setting")
        settings = self._read_settings()
        for index, encoded in updates.items():
            settings[index] = encoded
        self._action(6, 1, [{"piid": 1, "value": settings.hex()}])
        readback = self._read_settings()
        if any(readback[index] != encoded for index, encoded in updates.items()):
            raise CookerCommandError(
                "write_unconfirmed", "Settings write was not confirmed"
            )
