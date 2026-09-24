"""Select platform for Xiaomi Cooker."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import Cmc301Entity, RecipeParameterEntity, XiaomiMiioCookerEntity
from .errors import validation_error
from .profiles import get_cmc301_menu_key

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

    if coordinator.is_cmc301:
        async_add_entities(
            [
                PanelSleepSelect(coordinator, "panel_auto_off"),
                PanelRecipeSelect(coordinator, "panel_recipe"),
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
        return self.coordinator.displayed_menu

    @property
    def options(self) -> list[str]:
        """Return the available options."""
        if self.coordinator.cooking_active:
            return [self.current_option] if self.current_option is not None else []
        return self.coordinator.cooking_menu_options

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.coordinator.async_select_cooking_menu(option)


class RecipeTasteSelect(RecipeParameterEntity, SelectEntity):
    _attr_options: ClassVar[list[str]] = ["soft", "middle", "hard"]
    _attr_icon = "mdi:rice"

    @property
    def uses_default(self):
        if self.coordinator.cooking_active:
            return self.coordinator.displayed_menu not in (None, "other", "jingzhu")
        return not self.coordinator.supports_option("taste")

    @property
    def current_option(self):
        if self.uses_default:
            return "default"
        value = self.coordinator.displayed_parameter("taste")
        return (
            self._attr_options[value] if type(value) is int and 0 <= value < 3 else None
        )

    @property
    def options(self):
        if self.uses_default:
            return ["default"]
        if self.coordinator.cooking_active:
            return [self.current_option] if self.current_option is not None else []
        return self._attr_options

    async def async_select_option(self, option):
        if option == "default" and self.uses_default:
            return
        if self.uses_default:
            raise validation_error("invalid_taste")
        if option not in self._attr_options:
            raise validation_error("invalid_taste")
        self.coordinator.set_recipe_option("taste", self._attr_options.index(option))


class RecipeDurationSelect(RecipeParameterEntity, SelectEntity):
    _attr_icon = "mdi:timer-outline"

    @property
    def available(self):
        return super().available and (
            self.current_option is not None
            if self.coordinator.cooking_active
            else self.coordinator.supports_option("duration")
        )

    @property
    def options(self):
        if self.coordinator.cooking_active:
            return [self.current_option] if self.current_option is not None else []
        return self.coordinator.cooking_duration_options

    @property
    def current_option(self):
        value = self.coordinator.displayed_parameter("duration")
        return str(value) if value is not None else None

    async def async_select_option(self, option):
        if option not in self.options:
            raise validation_error("invalid_duration_option")
        self.coordinator.set_recipe_option("duration", int(option))


class PanelSleepSelect(Cmc301Entity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options: ClassVar[list[str]] = ["off", *map(str, range(2, 11))]

    @property
    def current_option(self):
        values = self.coordinator.data.properties
        if values.get("panel_auto_off") is False:
            return "off"
        duration = values.get("display_timeout")
        if (
            values.get("panel_auto_off") is True
            and type(duration) is int
            and 2 <= duration <= 10
        ):
            return str(duration)
        return None

    @property
    def available(self):
        return super().available and self.current_option is not None

    async def async_select_option(self, option):
        if option not in self.options:
            raise validation_error("invalid_duration_option")
        await self.coordinator.async_set_setting(
            "panel_sleep", "off" if option == "off" else int(option)
        )


class PanelRecipeSelect(Cmc301Entity, SelectEntity):
    @property
    def current_option(self):
        value = self.coordinator.data.properties.get("panel_recipe_id")
        return get_cmc301_menu_key(value) if type(value) is int else None

    @property
    def options(self):
        if self.coordinator.cooking_active:
            return [self.current_option] if self.current_option is not None else []
        recipes = self.coordinator.cooking_menu_options
        return [*recipes, "other"] if self.current_option == "other" else recipes

    async def async_select_option(self, option):
        # 'Other' represents a readback, never an instruction to overwrite the slot.
        await self.coordinator.async_select_panel_recipe(option)
