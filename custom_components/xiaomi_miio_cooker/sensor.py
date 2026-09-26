"""Sensor platform for Xiaomi Cooker."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import STATE_UNKNOWN, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .cmc301 import FAULTS
from .const import MODEL_CMC301, MODEL_NORMAL3
from .coordinator import XiaomiCookerConfigEntry
from .entity import XiaomiMiioCookerEntity
from .profiles import (
    COMMON_MENU_OPTIONS,
    COMMON_MENU_OTHER,
    get_cmc301_menu_key,
    get_menu_key,
    get_profiles_for_model,
)
from .stages import RICE_PHASES

CAMEL_CASE_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")
MODE_OPTIONS = ("unknown", "fine_cook", "quick_cook", "cook_congee", "keep_warm")
STATUS_OPTIONS = ("unknown", "idle", "running", "keep_warm", "busy")
BOOLEAN_OPTIONS = ("off", "on")


# Polls and writes are serialized per device by the coordinator/API locks.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class XiaomiCookerSensorDescription(SensorEntityDescription):
    """Describes a Xiaomi cooker sensor."""

    child: str | None = None
    attribute_name: str
    enum_options: tuple[str, ...] | None = None


SENSOR_DESCRIPTIONS: tuple[XiaomiCookerSensorDescription, ...] = (
    XiaomiCookerSensorDescription(
        key="mode",
        name="Mode",
        translation_key="mode",
        icon="mdi:pot-mix-outline",
        device_class=SensorDeviceClass.ENUM,
        attribute_name="mode",
        enum_options=MODE_OPTIONS,
    ),
    XiaomiCookerSensorDescription(
        key="status",
        name="Status",
        translation_key="status",
        icon="mdi:information-outline",
        device_class=SensorDeviceClass.ENUM,
        attribute_name="status",
        enum_options=STATUS_OPTIONS,
    ),
    XiaomiCookerSensorDescription(
        key="menu",
        name="Menu",
        translation_key="menu",
        icon="mdi:menu",
        device_class=SensorDeviceClass.ENUM,
        attribute_name="menu",
        enum_options=COMMON_MENU_OPTIONS,
    ),
    XiaomiCookerSensorDescription(
        key="temperature",
        name="Temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        attribute_name="temperature",
    ),
    XiaomiCookerSensorDescription(
        key="remaining",
        name="Remaining",
        translation_key="remaining",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        attribute_name="remaining",
    ),
    XiaomiCookerSensorDescription(
        key="duration",
        name="Duration",
        translation_key="duration",
        icon="mdi:timelapse",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        attribute_name="duration",
    ),
    XiaomiCookerSensorDescription(
        key="favorite",
        name="Favorite",
        translation_key="favorite",
        icon="mdi:star-cog-outline",
        device_class=SensorDeviceClass.ENUM,
        attribute_name="favorite",
        enum_options=COMMON_MENU_OPTIONS,
    ),
    XiaomiCookerSensorDescription(
        key="panel_display_auto_off",
        name="Panel display auto off",
        translation_key="panel_display_auto_off",
        icon="mdi:lightbulb-outline",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        attribute_name="panel_display_auto_off",
        enum_options=BOOLEAN_OPTIONS,
    ),
    XiaomiCookerSensorDescription(
        key="lid_open_warning",
        name="Lid open alarm",
        translation_key="lid_open_warning",
        icon="mdi:bell-ring-outline",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        attribute_name="lid_open_warning",
        enum_options=BOOLEAN_OPTIONS,
    ),
    XiaomiCookerSensorDescription(
        key="lid_open_timeout",
        name="Auto keep-warm lid open timeout",
        translation_key="lid_open_timeout",
        icon="mdi:timer-cog-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        attribute_name="lid_open_timeout",
    ),
    XiaomiCookerSensorDescription(
        key="rice_id",
        name="Rice ID",
        translation_key="rice_id",
        icon="mdi:rice",
        child="stage",
        attribute_name="rice_id",
    ),
    XiaomiCookerSensorDescription(
        key="taste",
        name="Taste",
        translation_key="taste",
        icon="mdi:pot-mix-outline",
        child="stage",
        attribute_name="taste",
    ),
    XiaomiCookerSensorDescription(
        key="taste_phase",
        name="Taste phase",
        translation_key="taste_phase",
        icon="mdi:flash-outline",
        child="stage",
        attribute_name="taste_phase",
    ),
    XiaomiCookerSensorDescription(
        key="stage_name",
        name="Stage name",
        translation_key="stage_name",
        icon="mdi:stairs",
        child="stage",
        attribute_name="name",
    ),
    XiaomiCookerSensorDescription(
        key="stage_description",
        name="Stage description",
        translation_key="stage_description",
        icon="mdi:stairs",
        child="stage",
        attribute_name="description",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiCookerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Xiaomi cooker sensors from a config entry."""
    coordinator = entry.runtime_data
    descriptions = SENSOR_DESCRIPTIONS
    if coordinator.is_cmc301:
        descriptions = cmc301_descriptions()
    elif entry.data.get("model") == MODEL_NORMAL3:
        descriptions = tuple(
            _rice_stage_description(description)
            if description.key in {"stage_name", "stage_description"}
            else description
            for description in descriptions
            if description.key
            not in {
                "mode",
                "menu",
                "duration",
                "taste",
                "taste_phase",
                "stage_description",
                "favorite",
                "panel_display_auto_off",
                "lid_open_warning",
                "lid_open_timeout",
            }
        )
    descriptions = (
        *descriptions,
        XiaomiCookerSensorDescription(
            key="current_menu",
            translation_key="current_menu",
            attribute_name="menu",
            device_class=SensorDeviceClass.ENUM,
            enum_options=(*coordinator.cooking_menu_options, "other"),
            icon="mdi:menu",
        ),
        XiaomiCookerSensorDescription(
            key="current_taste",
            translation_key="current_taste",
            attribute_name="taste",
            device_class=SensorDeviceClass.ENUM,
            enum_options=("soft", "middle", "hard", "default"),
            icon="mdi:rice",
        ),
        XiaomiCookerSensorDescription(
            key="current_duration",
            translation_key="current_duration",
            attribute_name="duration",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-outline",
        ),
    )
    async_add_entities(
        XiaomiCookerSensor(coordinator, description) for description in descriptions
    )


class XiaomiCookerSensor(XiaomiMiioCookerEntity, SensorEntity):
    """Representation of a Xiaomi cooker sensor."""

    entity_description: XiaomiCookerSensorDescription

    def __init__(
        self,
        coordinator,
        description: XiaomiCookerSensorDescription,
    ) -> None:
        """Initialize the sensor."""
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
        self._attr_device_class = description.device_class
        self._attr_icon = description.icon
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_entity_category = description.entity_category
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )

    @property
    def options(self) -> list[str] | None:
        """Return enum options for sensors with a bounded state set."""
        if self.entity_description.enum_options is None:
            return None

        if (
            not self.coordinator.is_cmc301
            and self.coordinator.recipe_codec is not None
            and self.entity_description.key in {"menu", "favorite"}
        ):
            return list(
                dict.fromkeys(
                    [
                        *self.entity_description.enum_options,
                        *self.coordinator.cooking_menu_options,
                    ]
                )
            )
        return list(self.entity_description.enum_options)

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        raw_value = self._get_raw_value()
        if self.entity_description.key in {"menu", "favorite"}:
            return self._normalize_menu_state(raw_value)

        if self.entity_description.enum_options is not None and raw_value is not None:
            normalized_value = self._normalize_enum_state(raw_value)
            if normalized_value in self.entity_description.enum_options:
                return normalized_value
            return STATE_UNKNOWN

        return raw_value

    @property
    def extra_state_attributes(self):
        """Keep stage provenance and numeric codes separate from display text."""
        if self.entity_description.key == "fault":
            return {"code": self.coordinator.data.properties.get("fault")}
        if self.entity_description.key not in {"stage_name", "stage_description"}:
            return None
        data = self.coordinator.data
        if data is None:
            return None
        stage = data.status.stage if data.status is not None else None
        attributes = {
            "description": stage.phase if stage is not None else None,
            "source": data.properties.get("stage_source"),
            "stage_code": stage.state if stage is not None else None,
        }
        if self.coordinator.is_cmc301:
            attributes["history_based"] = True
        elif isinstance(data.properties.get("stage_raw"), str):
            attributes["raw_stage"] = data.properties["stage_raw"]
        if self.coordinator.config_entry.data.get("model") == MODEL_NORMAL3:
            attributes["history_based"] = True
            attributes["phase_index"] = data.properties.get("history_phase_index")
        return attributes

    def _get_raw_value(self):
        """Return the raw value provided by the coordinator snapshot."""
        data = self.coordinator.data
        if data is None:
            return None

        key = self.entity_description.key
        if key in {"current_menu", "current_taste", "current_duration"}:
            if not self.coordinator.cooking_active:
                return None
            if key == "current_menu":
                return self.coordinator.displayed_menu
            if key == "current_duration":
                return data.status.duration
            menu = self.coordinator.displayed_menu
            if menu not in (None, "other", "jingzhu"):
                return "default"
            return {0: "soft", 1: "middle", 2: "hard"}.get(
                self.coordinator.displayed_parameter("taste")
            )
        if key == "fault":
            code = data.properties.get("fault")
            return FAULTS.get(code, "other") if type(code) is int else None

        if (
            self.coordinator.is_cmc301
            and self.entity_description.key in data.properties
        ):
            value = data.properties[self.entity_description.key]
            if self.entity_description.key == "texture":
                return {0: "soft", 1: "middle", 2: "hard"}.get(value)
            if self.entity_description.key == "recipe_type":
                return {0: "official", 1: "cloud", 2: "custom"}.get(value)
            return value

        if self.entity_description.key == "temperature":
            return data.temperature

        if self.entity_description.key == "panel_display_auto_off":
            return self._normalize_bool_state(
                self.coordinator.panel_display_auto_off_enabled
            )

        if self.entity_description.key == "lid_open_warning":
            return self._normalize_bool_state(self.coordinator.lid_open_warning_enabled)

        if self.entity_description.key == "lid_open_timeout":
            return self.coordinator.lid_open_timeout_minutes

        if data.status is None:
            return None

        state = data.status
        if self.entity_description.child is not None:
            state = getattr(state, self.entity_description.child, None)
            if state is None:
                return None

        return getattr(state, self.entity_description.attribute_name, None)

    def _normalize_menu_state(self, value: int | str | None) -> str | None:
        """Normalize menu IDs into stable enum keys with an other fallback."""
        if value is None:
            return None

        if isinstance(value, int):
            return (
                get_cmc301_menu_key(value)
                if self.coordinator.is_cmc301
                else get_menu_key(
                    value, self.coordinator.config_entry.data.get("model")
                )
            ) or COMMON_MENU_OTHER

        raw_value = str(value).strip().lower()
        if raw_value.isdigit():
            return self._normalize_menu_state(int(raw_value))

        return COMMON_MENU_OTHER

    @staticmethod
    def _normalize_enum_state(value: Enum | str) -> str:
        """Normalize enum state values to the lowercase format HA expects."""
        if isinstance(value, Enum):
            if isinstance(value.value, str):
                raw_value = value.value
            else:
                raw_value = value.name
        else:
            raw_value = str(value)

        normalized = CAMEL_CASE_PATTERN.sub("_", raw_value)
        normalized = normalized.replace("-", "_").replace(" ", "_")
        return normalized.lower()

    @staticmethod
    def _normalize_bool_state(value: bool | None) -> str | None:
        """Normalize a boolean state into an enum string."""
        if value is None:
            return None

        return "on" if value else "off"


def _rice_stage_description(description):
    return replace(
        description,
        attribute_name="phase",
        device_class=SensorDeviceClass.ENUM,
        enum_options=RICE_PHASES,
    )


def cmc301_descriptions():
    """Expose only feedback this model actually provides."""
    descriptions = []
    for description in SENSOR_DESCRIPTIONS:
        if description.key not in {
            "status",
            "remaining",
            "stage_name",
        }:
            continue
        if description.key in {"stage_name", "stage_description"}:
            description = _rice_stage_description(description)
        elif description.key == "mode":
            description = replace(
                description,
                enum_options=(*MODE_OPTIONS, "custom"),
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=False,
            )
        elif description.key == "status":
            description = replace(
                description,
                enum_options=(
                    *STATUS_OPTIONS,
                    "scheduled",
                    "error",
                    "updating",
                    "completed",
                ),
            )
        elif description.key == "menu":
            description = replace(
                description,
                enum_options=(
                    *(p.key for p in get_profiles_for_model(MODEL_CMC301)),
                    "other",
                ),
            )
        descriptions.append(description)
    descriptions.extend(
        (
            XiaomiCookerSensorDescription(
                key="fault",
                translation_key="fault",
                attribute_name="fault",
                entity_category=EntityCategory.DIAGNOSTIC,
                device_class=SensorDeviceClass.ENUM,
                enum_options=(*FAULTS.values(), "other"),
                icon="mdi:alert-circle-outline",
            ),
            XiaomiCookerSensorDescription(
                key="recorded_temperature",
                translation_key="recorded_temperature",
                attribute_name="recorded_temperature",
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            ),
        )
    )
    return tuple(descriptions)
