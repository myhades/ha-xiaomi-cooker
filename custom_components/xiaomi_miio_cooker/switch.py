"""Shared recipe options and device settings."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import CookerPropertyEntity, RecipeParameterEntity

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
    if coordinator.recipe_codec is not None:
        keys = (
            ("completion_notification", "all_modes_lit", "buzzer")
            if coordinator.is_cmc301
            else ("completion_notification", "lid_open_warning")
        )
        async_add_entities(CookerSettingSwitch(coordinator, key) for key in keys)


class CookerSettingSwitch(CookerPropertyEntity, SwitchEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key != "buzzer":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.settings_writable
            and self.reported_value is not None
        )

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
        return super().available and (
            self.is_on is not None
            if self.coordinator.cooking_active
            else self.coordinator.supports_option("auto_keep_warm")
        )

    @property
    def is_on(self):
        if self.coordinator.cooking_active:
            value = self.coordinator.data.properties.get("auto_keep_warm")
            return value if type(value) is bool else None
        options = self.coordinator.recipe_options
        return options.auto_keep_warm if options is not None else None

    @property
    def extra_state_attributes(self):
        return {"read_only": self.coordinator.cooking_active}

    async def async_turn_on(self, **kwargs):
        self.coordinator.set_recipe_option("auto_keep_warm", True)

    async def async_turn_off(self, **kwargs):
        self.coordinator.set_recipe_option("auto_keep_warm", False)
