"""Button platform for Xiaomi Cooker."""

from __future__ import annotations

from dataclasses import dataclass, replace

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import Cmc301Entity, XiaomiMiioCookerEntity

# Polls and writes are serialized per device by the coordinator/API locks.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class XiaomiCookerButtonDescription(ButtonEntityDescription):
    """Describes a Xiaomi cooker button entity."""


BUTTON_DESCRIPTIONS: tuple[XiaomiCookerButtonDescription, ...] = (
    XiaomiCookerButtonDescription(
        key="start_cooking",
        name="Start cooking",
        translation_key="start_cooking",
        icon="mdi:play",
    ),
    XiaomiCookerButtonDescription(
        key="stop_cooking",
        name="Stop cooking",
        translation_key="stop_cooking",
        icon="mdi:stop",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiCookerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Xiaomi cooker buttons from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        XiaomiCookerButton(coordinator, description)
        for description in BUTTON_DESCRIPTIONS
    )

    if coordinator.is_cmc301:
        async_add_entities([Cmc301PanelButton(coordinator, "save_panel_recipe")])


class XiaomiCookerButton(XiaomiMiioCookerEntity, ButtonEntity):
    """Representation of a Xiaomi cooker button."""

    entity_description: XiaomiCookerButtonDescription

    def __init__(self, coordinator, description: XiaomiCookerButtonDescription) -> None:
        """Initialize the button."""
        super().__init__(
            coordinator,
            unique_key=description.key,
            name=description.name or description.key,
            translation_key=description.translation_key,
        )
        self.entity_description = (
            replace(description, name=None)
            if description.translation_key is not None
            else description
        )
        self._attr_icon = description.icon

    async def async_press(self) -> None:
        """Handle button presses."""
        if self.entity_description.key == "start_cooking":
            await self.coordinator.async_start_selected_profile()
            return

        await self.coordinator.async_stop()


class Cmc301PanelButton(Cmc301Entity, ButtonEntity):
    @property
    def available(self):
        return super().available and self.coordinator.selected_recipe is not None

    async def async_press(self):
        await self.coordinator.async_set_panel_recipe()
