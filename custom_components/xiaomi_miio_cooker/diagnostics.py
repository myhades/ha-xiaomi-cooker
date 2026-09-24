"""Allowlisted, cached diagnostics: no credentials, identifiers or device I/O."""

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import XiaomiCookerConfigEntry

SAFE_PROPERTIES = {
    "status_code",
    "fault",
    "mode_code",
    "recipe_id",
    "duration",
    "remaining_seconds",
    "texture",
    "remote_control",
    "boiling",
    "history_samples",
    "recorded_temperature",
    "stage_source",
    "stage_raw",
    "history_phase_index",
    "buzzer",
    "panel_auto_off",
    "completion_notification",
    "all_modes_lit",
    "display_timeout",
    "panel_recipe_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: XiaomiCookerConfigEntry
) -> dict[str, Any]:
    """Export explicitly selected fields; never serialize the entry or API."""
    coordinator = entry.runtime_data
    snapshot = coordinator.data
    result: dict[str, Any] = {
        "model": entry.data.get("model"),
        "last_update_success": coordinator.last_update_success,
        "last_exception_type": type(coordinator.last_exception).__name__
        if coordinator.last_exception is not None
        else None,
        "selected_recipe": coordinator.selected_cooking_menu,
        "recipe_options": asdict(coordinator.recipe_options)
        if coordinator.recipe_options is not None
        else None,
    }
    if snapshot is not None:
        result["device"] = {
            "model": snapshot.device_info.model,
            "firmware_version": snapshot.device_info.firmware_version,
            "hardware_version": snapshot.device_info.hardware_version,
        }
        result["status"] = asdict(snapshot.status)
        result["settings"] = asdict(snapshot.settings) if snapshot.settings else None
        result["interaction_timeouts"] = (
            asdict(snapshot.interaction_timeouts)
            if snapshot.interaction_timeouts
            else None
        )
        result["temperature"] = snapshot.temperature
        result["properties"] = {
            key: value
            for key, value in snapshot.properties.items()
            if key in SAFE_PROPERTIES
        }
    return result
