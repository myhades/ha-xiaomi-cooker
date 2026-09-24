"""Select platform for Xiaomi Cooker."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import RecipeParameterEntity, XiaomiMiioCookerEntity
from .errors import validation_error

# Polls and writes are serialized per device by the coordinator/API locks.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class XiaomiCookerSelectDescription(SelectEntityDescription):
    """Describes a Xiaomi cooker select entity."""


SELECT_DESCRIPTIONS: tuple[XiaomiCookerSelectDescription, ...] = (
    XiaomiCookerSelectDescription(
        key="cooking_menu",
        name="Cooking menu",
        translation_key="cooking_menu",
        icon="mdi:format-list-bulleted-square",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiCookerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Xiaomi cooker select entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        XiaomiCookerSelect(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    )

    if coordinator.recipe_codec is not None:
        async_add_entities(
            [
                RecipeTasteSelect(coordinator, "next_taste"),
                RecipeDurationSelect(coordinator, "next_duration"),
            ]
        )


class XiaomiCookerSelect(XiaomiMiioCookerEntity, SelectEntity):
    """Representation of a Xiaomi cooker select entity."""

    entity_description: XiaomiCookerSelectDescription

    def __init__(self, coordinator, description: XiaomiCookerSelectDescription) -> None:
        """Initialize the select entity."""
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

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self.coordinator.selected_cooking_menu

    @property
    def options(self) -> list[str]:
        """Return the available options."""
        return self.coordinator.cooking_menu_options

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.coordinator.async_select_cooking_menu(option)


class RecipeTasteSelect(RecipeParameterEntity, SelectEntity):
    _attr_options: ClassVar[list[str]] = ["soft", "middle", "hard"]

    @property
    def available(self):
        return super().available and self.coordinator.supports_option("taste")

    @property
    def current_option(self):
        options = self.coordinator.recipe_options
        return self._attr_options[options.taste] if options is not None else None

    async def async_select_option(self, option):
        if option not in self._attr_options:
            raise validation_error("invalid_taste")
        self.coordinator.set_recipe_option("taste", self._attr_options.index(option))


class RecipeDurationSelect(RecipeParameterEntity, SelectEntity):
    _attr_icon = "mdi:timer-outline"

    @property
    def available(self):
        return super().available and self.coordinator.supports_option("duration")

    @property
    def options(self):
        return self.coordinator.cooking_duration_options

    @property
    def current_option(self):
        options = self.coordinator.recipe_options
        return str(options.duration) if options is not None else None

    async def async_select_option(self, option):
        if option not in self.options:
            raise validation_error("invalid_duration_option")
        self.coordinator.set_recipe_option("duration", int(option))
