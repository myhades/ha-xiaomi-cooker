"""The Xiaomi Cooker integration."""

from __future__ import annotations

import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import XiaomiMiioCookerApi, build_unique_id
from .const import (
    CONF_MODEL,
    DOMAIN,
    MODEL_CMC301,
    MODEL_NORMAL3,
    PLATFORMS,
    RAW_DIAGNOSTIC_PROPERTIES,
)
from .coordinator import XiaomiCookerConfigEntry, XiaomiMiioCookerCoordinator
from .profiles import get_profiles_for_model
from .services import async_register_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Xiaomi cooker integration."""
    await async_register_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: XiaomiCookerConfigEntry
) -> bool:
    """Set up Xiaomi cooker from a config entry."""
    api = XiaomiMiioCookerApi(
        host=entry.data[CONF_HOST],
        token=entry.data[CONF_TOKEN],
        model=entry.data.get(CONF_MODEL),
    )
    profiles = await hass.async_add_executor_job(
        get_profiles_for_model,
        entry.data.get(CONF_MODEL),
    )
    coordinator = XiaomiMiioCookerCoordinator(hass, entry, api, profiles)
    await coordinator.async_config_entry_first_refresh()
    expected_unique_id = build_unique_id(
        coordinator.data.device_info.mac_address,
        coordinator.data.device_info.model or entry.data.get(CONF_MODEL),
        entry.data.get(CONF_HOST),
    )
    if entry.unique_id != expected_unique_id:
        hass.config_entries.async_update_entry(
            entry,
            unique_id=expected_unique_id,
        )
        coordinator.device_unique_id = expected_unique_id

    entry.runtime_data = coordinator
    _remove_replaced_duration_number(
        hass, entry, coordinator.device_unique_id, entry.data.get(CONF_MODEL)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_replaced_duration_number(hass, entry, device_unique_id, model=None):
    """Remove only this entry's controls superseded by shared selectors."""
    registry = er.async_get(hass)
    replaced = [("number", "next_duration")]
    if model in {MODEL_CMC301, MODEL_NORMAL3}:
        replaced.extend(
            ("sensor", key) for key in ("mode", "menu", "duration", "stage_description")
        )
        replaced.extend(
            ("sensor", key)
            for key in (
                ("texture",) if model == MODEL_CMC301 else ("taste", "taste_phase")
            )
        )
    if model == MODEL_CMC301:
        replaced.extend(("sensor", key) for key in RAW_DIAGNOSTIC_PROPERTIES)
        replaced.extend(
            [
                ("switch", "panel_auto_off"),
                ("number", "display_timeout"),
                ("button", "save_panel_recipe"),
            ]
        )
    elif model == MODEL_NORMAL3:
        replaced.extend(
            ("sensor", key)
            for key in (
                "favorite",
                "panel_display_auto_off",
                "lid_open_warning",
                "lid_open_timeout",
            )
        )
    for platform, key in replaced:
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, f"{device_unique_id}_{key}"
        )
        if entity_id is not None:
            old = registry.async_get(entity_id)
            if old is not None and old.config_entry_id == entry.entry_id:
                registry.async_remove(entity_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: XiaomiCookerConfigEntry
) -> bool:
    """Unload a config entry."""
    # HA clears runtime_data and invokes the entry's unload callbacks.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
