"""Integration actions and compatible device target resolution."""

from __future__ import annotations

import asyncio

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import ATTR_PROFILE, DOMAIN, SERVICE_START, SERVICE_START_RECIPE
from .coordinator import XiaomiMiioCookerCoordinator
from .errors import recipe_error, validation_error

SERVICE_START_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_PROFILE): cv.string,
    }
)

SERVICE_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("recipe"): cv.string,
        vol.Optional("duration"): vol.All(int, vol.Range(min=1, max=1440)),
        vol.Optional("finish_in"): vol.All(int, vol.Range(min=0, max=1439)),
        vol.Optional("taste"): vol.In(["soft", "middle", "hard"]),
        vol.Optional("auto_keep_warm"): cv.boolean,
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    if hass.services.has_service(DOMAIN, SERVICE_START):
        return

    async def async_start_service(call: ServiceCall) -> None:
        """Start a cooking profile on the target cooker."""
        coordinators = _async_resolve_coordinators(hass, call)
        try:
            for coordinator in coordinators:
                coordinator.api.validate_profile(call.data[ATTR_PROFILE])
        except ValueError as err:
            raise recipe_error(err) from err
        await asyncio.gather(
            *(
                coordinator.async_start(call.data[ATTR_PROFILE])
                for coordinator in coordinators
            )
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START,
        async_start_service,
        schema=SERVICE_START_SCHEMA,
    )

    async def async_recipe_service(call: ServiceCall) -> None:
        coordinators = _async_resolve_coordinators(hass, call)
        options = {
            key: call.data[key]
            for key in ("duration", "finish_in", "taste", "auto_keep_warm")
            if key in call.data
        }
        if "taste" in options:
            options["taste"] = ["soft", "middle", "hard"].index(options["taste"])
        # Validate every target before starting any of them.
        requests = [
            (coordinator, coordinator.prepare_recipe(call.data["recipe"], options))
            for coordinator in coordinators
        ]
        await asyncio.gather(
            *(coordinator.async_start(profile) for coordinator, profile in requests)
        )

    hass.services.async_register(
        DOMAIN, SERVICE_START_RECIPE, async_recipe_service, schema=SERVICE_RECIPE_SCHEMA
    )


def _async_resolve_coordinators(
    hass: HomeAssistant,
    call: ServiceCall,
) -> list[XiaomiMiioCookerCoordinator]:
    """Resolve target coordinators for a service call."""
    coordinators = {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    }
    device_ids = call.data.get(ATTR_DEVICE_ID)

    if not device_ids:
        if not coordinators:
            raise validation_error("no_loaded_device")
        if len(coordinators) == 1:
            return list(coordinators.values())

        raise validation_error("multiple_devices")

    device_registry = dr.async_get(hass)
    resolved_entry_ids: set[str] = set()

    for device_id in device_ids:
        # HA 2026.8 already exposes split devices for saved composite IDs.
        devices = device_registry.async_get_devices_for_composite_device_id(device_id)
        if not devices:
            device = device_registry.async_get(device_id)
            if device is None:
                raise validation_error("device_not_found")
            devices = [device]
        matches = {device.config_entry_id for device in devices} & coordinators.keys()
        if not matches:
            raise validation_error("device_not_loaded")
        if len(matches) != 1:
            raise validation_error("multiple_devices")
        matched_entry_id = matches.pop()

        resolved_entry_ids.add(matched_entry_id)

    return [coordinators[entry_id] for entry_id in resolved_entry_ids]
