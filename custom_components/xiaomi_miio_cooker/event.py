"""A single completion event per observed cooking cycle."""

from typing import ClassVar

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaomiCookerConfigEntry
from .entity import XiaomiMiioCookerEntity
from .profiles import get_cmc301_menu_key, get_menu_key

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiCookerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([CookingFinishedEvent(entry.runtime_data)])


class CookingFinishedEvent(XiaomiMiioCookerEntity, EventEntity):
    """Do not mistake stopping, reconnecting or loading old state for completion."""

    _attr_event_types: ClassVar[list[str]] = ["finished"]
    _attr_icon = "mdi:pot-steam-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "cooking_finished", None, "cooking_finished")
        self._previous = coordinator.data
        self._armed = self._is_cooking(self._previous)
        self._cancelled = False
        self._stop_revision = coordinator.stop_revision

    @staticmethod
    def _is_cooking(data):
        return (
            data is not None
            and data.status.status in ("running", "scheduled")
            and type(data.status.menu) is int
            and data.status.menu > 0
            and data.status.menu != 4
            and not data.properties.get("cooking_finished", False)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success:
            self._previous = None
            self._armed = False
        else:
            self._observe(self.coordinator.data)
        super()._handle_coordinator_update()

    def _observe(self, data):
        previous, self._previous = self._previous, data
        stopped = self._stop_revision != self.coordinator.stop_revision
        self._stop_revision = self.coordinator.stop_revision
        if previous is None:
            # Establish a fresh baseline after connection loss. Never replay a
            # completion that may have happened while HA could not observe it.
            self._armed = self._is_cooking(data) and not stopped
            self._cancelled = stopped
            return
        if stopped:
            self._cancelled = True
            self._armed = False
        if data.status.menu != previous.status.menu:
            self._armed = False
        cooking = self._is_cooking(data)
        finished = data.properties.get("cooking_finished") is True
        if cooking:
            if not stopped and (
                not self._is_cooking(previous)
                or data.status.menu != previous.status.menu
            ):
                self._cancelled = False
            if not self._cancelled:
                self._armed = True
        elif finished:
            if self._armed and not self._cancelled:
                menu = data.status.menu
                recipe = (
                    get_cmc301_menu_key(menu)
                    if self.coordinator.is_cmc301
                    else get_menu_key(menu, self.coordinator.config_entry.data["model"])
                )
                self._trigger_event(
                    "finished",
                    {
                        "recipe": recipe or "other",
                        "keep_warm_type": data.properties.get("keep_warm_type"),
                    },
                )
            self._armed = False
        else:
            self._armed = False
            self._cancelled = False
