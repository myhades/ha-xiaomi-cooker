"""CMC301 scheduled completion and display settings."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import Cmc301Entity
from .errors import validation_error

# Polls and writes are serialized per device by the coordinator/API locks.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiCookerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.is_cmc301:
        async_add_entities(
            Cmc301Number(coordinator, key) for key in ("finish_in", "display_timeout")
        )


class Cmc301Number(Cmc301Entity, NumberEntity):
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key):
        # Recipe preparation must not share the feedback sensor's unique key.
        super().__init__(
            coordinator, "next_" + key if key != "display_timeout" else key
        )
        self.option = key
        if key == "display_timeout":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self):
        return super().available and (
            self.reported_value is not None
            if self.option == "display_timeout"
            else not self.coordinator.cooking_active
            and self.coordinator.supports_option(self.option)
        )

    @property
    def native_value(self):
        if self.option == "display_timeout":
            return self.reported_value
        options = self.coordinator.recipe_options
        return getattr(options, self.option, None)

    @property
    def native_min_value(self):
        if self.option == "display_timeout":
            return 2
        return 0

    @property
    def native_max_value(self):
        if self.option == "display_timeout":
            return 10
        return 1439

    async def async_set_native_value(self, value):
        if not float(value).is_integer():
            raise validation_error("whole_minutes")
        if self.option == "display_timeout":
            await self.coordinator.async_set_setting(self.option, int(value))
        else:
            self.coordinator.set_recipe_option(self.option, int(value))
