"""CMC301 scheduled completion and display settings."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
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
        async_add_entities(Cmc301Number(coordinator, key) for key in ("finish_in",))


class Cmc301Number(Cmc301Entity, NumberEntity):
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key):
        # Recipe preparation must not share the feedback sensor's unique key.
        super().__init__(coordinator, "next_" + key)
        self.option = key

    @property
    def available(self):
        return super().available and (
            not self.coordinator.cooking_active
            and self.coordinator.supports_option(self.option)
        )

    @property
    def native_value(self):
        options = self.coordinator.recipe_options
        return getattr(options, self.option, None)

    @property
    def native_min_value(self):
        return 0

    @property
    def native_max_value(self):
        return 1439

    async def async_set_native_value(self, value):
        if not float(value).is_integer():
            raise validation_error("whole_minutes")
        self.coordinator.set_recipe_option(self.option, int(value))
