"""Shared entity definitions for Xiaomi Cooker."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import normalize_mac
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER


class XiaomiMiioCookerEntity(CoordinatorEntity):
    """Base entity for Xiaomi cooker entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        unique_key: str,
        name: str | None,
        translation_key: str | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        if translation_key is not None:
            self._attr_translation_key = translation_key
        elif name is not None:
            self._attr_name = name
        self._suggested_object_id = f"xiaomi_rice_cooker_{unique_key}"
        self._attr_unique_id = f"{coordinator.device_unique_id}_{unique_key}"

    @property
    def suggested_object_id(self) -> str | None:
        """Return the default object ID used for entity_id generation."""
        return self._suggested_object_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        metadata = self.coordinator.data.device_info
        device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, self.coordinator.device_unique_id)},
            "manufacturer": MANUFACTURER,
            "name": DEFAULT_NAME,
        }

        if metadata.model:
            device_info["model"] = metadata.model
        if metadata.firmware_version:
            device_info["sw_version"] = metadata.firmware_version
        if metadata.hardware_version:
            device_info["hw_version"] = metadata.hardware_version

        mac_address = normalize_mac(metadata.mac_address)
        if mac_address:
            device_info["connections"] = {(CONNECTION_NETWORK_MAC, mac_address)}

        return device_info


class RecipeParameterEntity(XiaomiMiioCookerEntity):
    """Shared identity for next-cook controls on supported models."""

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key, None, key)
        self.key = key


class Cmc301Entity(RecipeParameterEntity):
    """Base for CMC301 device settings and feedback."""

    @property
    def reported_value(self):
        data = self.coordinator.data
        return data.properties.get(self.key) if data is not None else None
