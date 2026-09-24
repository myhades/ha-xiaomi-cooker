"""Shared next-cook keep-warm option and CMC301 device switches."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import Cmc301Entity, RecipeParameterEntity

# Polls and writes are serialized per device by the coordinator/API locks.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiCookerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.recipe_codec is not None:
        async_add_entities([RecipeKeepWarmSwitch(coordinator, "next_auto_keep_warm")])
    if coordinator.is_cmc301:
        async_add_entities(
            Cmc301Switch(coordinator, key)
            for key in (
                "completion_notification",
                "all_modes_lit",
                "buzzer",
            )
        )


class Cmc301Switch(Cmc301Entity, SwitchEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key != "buzzer":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self):
        return super().available and self.reported_value is not None

    @property
    def is_on(self):
        return self.reported_value

    async def _set(self, value):
        await self.coordinator.async_set_setting(self.key, value)

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)


class RecipeKeepWarmSwitch(RecipeParameterEntity, SwitchEntity):
    @property
    def available(self):
        return (
            super().available
            and not self.coordinator.cooking_active
            and self.coordinator.supports_option("auto_keep_warm")
        )

    @property
    def is_on(self):
        options = self.coordinator.recipe_options
        return options.auto_keep_warm if options is not None else None

    async def async_turn_on(self, **kwargs):
        self.coordinator.set_recipe_option("auto_keep_warm", True)

    async def async_turn_off(self, **kwargs):
        self.coordinator.set_recipe_option("auto_keep_warm", False)
