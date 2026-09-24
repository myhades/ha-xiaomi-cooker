"""Local MIoT backend for xiaomi.cooker.cmc301 only."""

from __future__ import annotations

import re
from time import monotonic

from miio import DeviceException

from .cmc301_profile import default_options, encode_profile, validate_bundled_profile
from .exceptions import CookerCommandError
from .models import CookerData, CookerStatusData
from .stages import history_payload, rice_history_stage

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
    "buzzer": (2, 32),
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
        return CookerData(
            device_info=self.metadata,
            status=CookerStatusData(
                mode=MODES.get(values["mode_code"], "unknown"),
                status=STATES.get(values["status_code"], "unknown"),
                menu=values["recipe_id"],
                remaining=remaining / 60
                if type(remaining) is int and remaining >= 0
                else None,
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
        if key == "buzzer":
            if type(value) is not bool:
                raise ValueError("Buzzer must be a boolean")
            result = self.device.send(
                "set_properties",
                [{"did": "miot", "siid": 2, "piid": 32, "value": value}],
                retry_count=0,
            )
            if (
                not isinstance(result, list)
                or len(result) != 1
                or result[0].get("code") != 0
            ):
                raise CookerCommandError("write_unconfirmed", "Buzzer write failed")
            if self._read({key: PROPERTIES[key]})[key] != value:
                raise CookerCommandError(
                    "write_unconfirmed", "Buzzer write was not confirmed"
                )
            return
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
