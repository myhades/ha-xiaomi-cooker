"""Legacy cooker backend; preserve established control and state semantics."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from time import monotonic
from typing import Any

from miio import Cooker, DeviceException

from .const import MODEL_NORMAL3, TEMPERATURE_HISTORY_MIN_INTERVAL_SECONDS
from .models import (
    CookerData,
    CookerDeviceMetadata,
    CookerInteractionTimeoutsData,
    CookerSettingsData,
    CookerStageData,
    CookerStatusData,
)
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

        return CookerData(
            device_info=self.metadata,
            status=status,
            settings=_build_settings_data(getattr(raw_status, "settings", None)),
            interaction_timeouts=_build_interaction_timeouts_data(
                getattr(raw_status, "interaction_timeouts", None)
            ),
            temperature=temperature,
            properties={
                "stage_source": "temperature_history" if normal3 else "device_stage",
                "stage_raw": raw_data.get("stage"),
                "history_phase_index": phase.state
                if normal3 and phase is not None
                else None,
            },
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
