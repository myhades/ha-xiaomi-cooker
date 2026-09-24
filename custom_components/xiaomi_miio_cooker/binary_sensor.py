"""CMC301 feedback: remote permission and water boiling, never lid state."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import Cmc301Entity

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
            Cmc301BinarySensor(coordinator, key)
            for key in ("remote_control", "boiling")
        )


class Cmc301BinarySensor(Cmc301Entity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.reported_value
