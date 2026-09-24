"""Legacy cooker backend; preserve established control and state semantics."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from time import monotonic
from typing import Any

from miio import Cooker, DeviceException

from .const import MODEL_NORMAL3, TEMPERATURE_HISTORY_MIN_INTERVAL_SECONDS
from .exceptions import CookerCommandError
from .models import (
    CookerData,
    CookerDeviceMetadata,
    CookerInteractionTimeoutsData,
    CookerSettingsData,
    CookerStageData,
    CookerStatusData,
)
from .normal3_profile import panel_profile
from .stages import history_payload, rice_history_stage

_LOGGER = logging.getLogger(__name__)


def _build_stage_data(
    stage: Any, *, legacy_text: bool = True
) -> CookerStageData | None:
    """Convert a python-miio stage object into an immutable snapshot."""
    if stage is None:
        return None

    try:
        return CookerStageData(
            state=getattr(stage, "state", None),
            rice_id=getattr(stage, "rice_id", None),
            taste=getattr(stage, "taste", None),
            taste_phase=getattr(stage, "taste_phase", None),
            name=getattr(stage, "name", None) if legacy_text else None,
            description=getattr(stage, "description", None) if legacy_text else None,
        )
    except ValueError, TypeError, IndexError, AttributeError:
        # One malformed optional stage must not discard the main cooker status.
        return None


def _build_status_data(status: Any, model: str | None = None) -> CookerStatusData:
    """Convert a python-miio status object into an immutable snapshot."""
    raw_data = getattr(status, "data", {}) or {}
    raw_func = str(raw_data.get("func", "")).lower()
    raw_menu = str(raw_data.get("menu", "")).lower()
    raw_stage = raw_data.get("stage")
    stage = None
    # python-miio checks only length before parsing the stage's hex fields.
    if "stage" not in raw_data or (
        isinstance(raw_stage, str) and re.fullmatch(r"[0-9a-fA-F]{10}", raw_stage)
    ):
        try:
            stage = _build_stage_data(
                getattr(status, "stage", None), legacy_text=model != MODEL_NORMAL3
            )
        except ValueError, TypeError, IndexError, AttributeError:
            stage = None

    return CookerStatusData(
        mode=_map_cook_mode(raw_menu),
        status=_map_work_status(raw_func),
        menu=_parse_menu(raw_menu),
        remaining=getattr(status, "remaining", None),
        duration=getattr(status, "duration", None),
        favorite=getattr(status, "favorite", None),
        stage=stage,
    )


def _parse_menu(raw_menu: str) -> int | None:
    """Parse the raw menu value into an integer."""
    if not raw_menu:
        return None

    try:
        return int(raw_menu, 16)
    except ValueError:
        return None


def _map_cook_mode(raw_menu: str) -> str:
    """Map the raw cooker menu value to a stable cook mode enum."""
    return {
        "0001": "fine_cook",
        "0002": "quick_cook",
        "0003": "cook_congee",
        "0004": "keep_warm",
    }.get(raw_menu, "unknown")


def _map_work_status(raw_func: str) -> str:
    """Map the raw func value to a stable work status enum."""
    return {
        "waiting": "idle",
        "running": "running",
        "cooking": "running",
        "autokeepwarm": "keep_warm",
        "keepwarm": "keep_warm",
        "keep_temp": "keep_warm",
        "finish": "keep_warm",
        "finisha": "keep_warm",
        "precook": "busy",
        "set02": "busy",
        "start": "busy",
        "startp": "busy",
        "resume": "busy",
        "resumep": "busy",
    }.get(raw_func, "unknown")


def _build_settings_data(settings: Any) -> CookerSettingsData | None:
    """Convert python-miio settings into an immutable snapshot."""
    if settings is None:
        return None

    return CookerSettingsData(
        led_on=getattr(settings, "led_on", None),
        lid_open_warning=getattr(settings, "lid_open_warning", None),
        lid_open_warning_delayed=getattr(settings, "lid_open_warning_delayed", None),
    )


def _build_interaction_timeouts_data(
    interaction_timeouts: Any,
) -> CookerInteractionTimeoutsData | None:
    """Convert python-miio interaction timeouts into an immutable snapshot."""
    if interaction_timeouts is None:
        return None

    return CookerInteractionTimeoutsData(
        led_off=getattr(interaction_timeouts, "led_off", None),
        lid_open=getattr(interaction_timeouts, "lid_open", None),
        lid_open_warning=getattr(interaction_timeouts, "lid_open_warning", None),
    )


class LegacyCookerBackend:
    """Keep old model RPCs isolated from MIoT devices."""

    def __init__(self, host: str, token: str, metadata: CookerDeviceMetadata) -> None:
        self._cooker = Cooker(host, token)
        self.metadata = metadata
        self._last_temperature_history_fetch: float | None = None
        self._cached_temperature_from_history: int | None = None
        self._last_known_temperature: int | None = None
        self._history_context = None
        self._history_phase = None
        self._history_interval = TEMPERATURE_HISTORY_MIN_INTERVAL_SECONDS

    def fetch_data(self) -> CookerData:
        """Fetch legacy status without changing existing enum mappings."""
        raw_status = self._cooker.status()
        status = _build_status_data(raw_status, self.metadata.model)
        raw_data = getattr(raw_status, "data", {}) or {}
        normal3 = self.metadata.model == MODEL_NORMAL3
        # normal3 plugin 11030 shows curve phases only for rice while running.
        show_rice_phase = (
            normal3 and raw_data.get("func") == "running" and status.menu in (1, 2)
        )
        if normal3:
            context = (raw_data.get("func"), status.menu)
            if context != self._history_context:
                self._invalidate_history()
                self._history_context = context
            self._history_interval = (
                30 if show_rice_phase else TEMPERATURE_HISTORY_MIN_INTERVAL_SECONDS
            )
        temperature = getattr(raw_status, "temperature", None)
        if temperature is None or show_rice_phase:
            history_temperature = self._get_temperature_from_history()
            if temperature is None:
                temperature = history_temperature
        if normal3:
            phase = self._history_phase if show_rice_phase else None
            if status.stage is not None:
                status = replace(
                    status,
                    stage=replace(status.stage, phase=phase.phase if phase else None),
                )
            elif phase is not None:
                # History can be valid even when the optional raw stage is not.
                status = replace(status, stage=replace(phase, state=None))
        if temperature is None and not normal3:
            temperature = self._last_known_temperature
        else:
            self._last_known_temperature = temperature

        properties = {
            "stage_source": "temperature_history" if normal3 else "device_stage",
            "stage_raw": raw_data.get("stage"),
            "history_phase_index": phase.state
            if normal3 and phase is not None
            else None,
        }
        if normal3:
            settings = _build_settings_data(getattr(raw_status, "settings", None))
            timeouts = _build_interaction_timeouts_data(
                getattr(raw_status, "interaction_timeouts", None)
            )
            properties.update(
                {
                    "auto_keep_warm": bool(int(raw_data["setting"][:2], 16) & 4)
                    if isinstance(raw_data.get("setting"), str)
                    and re.fullmatch(r"[0-9a-fA-F]{4}", raw_data["setting"])
                    else None,
                    "panel_recipe_id": status.favorite,
                    "panel_auto_off": not settings.led_on
                    if settings and settings.led_on is not None
                    else None,
                    "display_timeout": timeouts.led_off if timeouts else None,
                    "lid_open_warning": settings.lid_open_warning_delayed
                    if settings
                    else None,
                    "lid_open_timeout": timeouts.lid_open if timeouts else None,
                }
            )
            try:
                properties["completion_notification"] = self._read_push()
            except DeviceException:
                properties["completion_notification"] = None
        return CookerData(
            device_info=self.metadata,
            status=status,
            settings=_build_settings_data(getattr(raw_status, "settings", None)),
            interaction_timeouts=_build_interaction_timeouts_data(
                getattr(raw_status, "interaction_timeouts", None)
            ),
            temperature=temperature,
            properties=properties,
        )

    def _read_push(self) -> bool:
        result = self._cooker.send("get_setting", ["en_push"], retry_count=0)
        if (
            not isinstance(result, list)
            or not result
            or not isinstance(result[0], str)
            or not re.fullmatch(r"[0-9a-fA-F]{4}", result[0])
            or result[0][:2] not in ("00", "01")
        ):
            raise DeviceException("Invalid completion notification setting")
        return result[0][:2] == "00"

    def _idle_snapshot(self):
        if self.metadata.model != MODEL_NORMAL3:
            raise ValueError("Settings are only supported for normal3")
        status = self._cooker.status()
        if status.data.get("func") != "waiting":
            raise CookerCommandError("cooker_busy", "Cooker must be idle")
        return status

    def _write(self, method, params):
        if self._cooker.send(method, params, retry_count=0) != ["ok"]:
            raise CookerCommandError(
                "write_unconfirmed", "Setting write was not confirmed"
            )

    def set_panel_recipe(self, profile: str) -> None:
        encoded = panel_profile(profile)
        self._idle_snapshot()
        self._write("set_menu", [encoded])
        if self._cooker.status().favorite != int(encoded[:4], 16):
            raise CookerCommandError(
                "write_unconfirmed", "Custom recipe was not confirmed"
            )

    def set_setting(self, key: str, value) -> None:
        if key == "panel_sleep":
            if value != "off" and (type(value) is not int or not 5 <= value <= 10):
                raise ValueError("normal3 panel sleep must be off or 5-10 minutes")
        elif key == "lid_open_timeout":
            if type(value) is not int or value not in (2, 4, 6, 8, 10):
                raise ValueError("Lid timeout must be 2, 4, 6, 8 or 10 minutes")
        elif (
            key not in ("lid_open_warning", "completion_notification")
            or type(value) is not bool
        ):
            raise ValueError("Unsupported normal3 setting")
        status = self._idle_snapshot()
        if key == "completion_notification":
            self._write("set_setting", ["00" if value else "01", "00", ""])
            if self._read_push() != value:
                raise CookerCommandError(
                    "write_unconfirmed", "Notification setting was not confirmed"
                )
            return
        raw_settings, raw_delays = status.data.get("setting"), status.data.get("delay")
        if (
            not isinstance(raw_settings, str)
            or not re.fullmatch(r"[0-9a-fA-F]{4}", raw_settings)
            or not isinstance(raw_delays, str)
            or not re.fullmatch(r"[0-9a-fA-F]{6}", raw_delays)
        ):
            raise DeviceException("Invalid interaction settings")
        original = int(raw_settings[:2], 16)
        flags = ((original & 2) >> 1) | ((original & 8) >> 2) | ((original & 16) >> 2)
        delays = bytearray.fromhex(raw_delays)
        if key == "panel_sleep":
            flags = flags | 1 if value == "off" else flags & ~1
            if value != "off":
                delays[0] = value
        elif key == "lid_open_warning":
            flags = flags | 4 if value else flags & ~4
        else:
            delays[1] = value
        # The plugin sends a single comma-separated string, not four arguments.
        self._write("set_interaction", [",".join(f"{v:x}" for v in (flags, *delays))])
        actual = self._cooker.status().data
        expected = (
            (original & ~0x1A)
            | ((flags & 1) << 1)
            | ((flags & 2) << 2)
            | ((flags & 4) << 2)
        )
        if (
            actual.get("setting", "").lower()
            != f"{expected:02x}" + raw_settings[2:].lower()
            or actual.get("delay", "").lower() != delays.hex()
        ):
            raise CookerCommandError(
                "write_unconfirmed", "Interaction settings were not confirmed"
            )

    def _get_temperature_from_history(self) -> int | None:
        """Read cached temperature history and throttle expensive updates."""
        now = monotonic()
        if (
            self._last_temperature_history_fetch is not None
            and now - self._last_temperature_history_fetch < self._history_interval
        ):
            return self._cached_temperature_from_history

        self._last_temperature_history_fetch = now
        try:
            temperature_history = self._cooker.get_temperature_history()
            if self.metadata.model == MODEL_NORMAL3:
                payload = history_payload(getattr(temperature_history, "raw", None))
                self._history_phase = rice_history_stage(payload)
                temperatures = [value for value in payload if value != 0xAA]
            else:
                temperatures = getattr(temperature_history, "temperatures", None)
        except (DeviceException, ValueError, TypeError) as err:
            _LOGGER.debug("Unable to refresh cooker temperature history: %s", err)
            self._cached_temperature_from_history = None
            self._history_phase = None
            return None

        self._last_temperature_history_fetch = now
        self._cached_temperature_from_history = (
            temperatures[-1] if temperatures else None
        )
        return self._cached_temperature_from_history

    def _invalidate_history(self) -> None:
        self._last_temperature_history_fetch = None
        self._cached_temperature_from_history = None
        self._history_phase = None

    def start(self, profile: str) -> Any:
        """Start a cooking profile."""
        try:
            return self._cooker.start(profile)
        finally:
            if self.metadata.model == MODEL_NORMAL3:
                self._invalidate_history()

    def stop(self) -> Any:
        """Stop the current cooking process."""
        try:
            return self._cooker.stop()
        finally:
            if self.metadata.model == MODEL_NORMAL3:
                self._invalidate_history()
