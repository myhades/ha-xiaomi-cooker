"""Shared snapshots and stable device identity helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import DEFAULT_NAME, DOMAIN


@dataclass(slots=True, frozen=True)
class CookerDeviceMetadata:
    """Static metadata about a Xiaomi cooker."""

    model: str | None
    firmware_version: str | None
    hardware_version: str | None
    mac_address: str | None


@dataclass(slots=True, frozen=True)
class CookerData:
    """Combined runtime data for the coordinator."""

    device_info: CookerDeviceMetadata
    status: CookerStatusData
    settings: CookerSettingsData | None
    interaction_timeouts: CookerInteractionTimeoutsData | None
    temperature: Any | None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class CookerStageData:
    """Runtime stage data used by the exposed sensors."""

    state: Any
    rice_id: Any
    taste: Any
    taste_phase: Any
    name: Any
    description: Any
    phase: str | None = None


@dataclass(slots=True, frozen=True)
class CookerStatusData:
    """Runtime cooker data used by the exposed sensors."""

    mode: Any
    status: Any
    menu: Any
    remaining: Any
    duration: Any
    favorite: Any
    stage: CookerStageData | None


@dataclass(slots=True, frozen=True)
class CookerSettingsData:
    """Cooker settings exposed by python-miio."""

    led_on: bool | None
    lid_open_warning: bool | None
    lid_open_warning_delayed: bool | None


@dataclass(slots=True, frozen=True)
class CookerInteractionTimeoutsData:
    """Cooker interaction timeout settings exposed by python-miio."""

    led_off: int | None
    lid_open: int | None
    lid_open_warning: int | None


def normalize_mac(mac_address: str | None) -> str | None:
    """Normalize a MAC address into aa:bb:cc:dd:ee:ff form."""
    if not mac_address:
        return None

    raw_mac = mac_address.lower().replace("-", "").replace(":", "")
    if len(raw_mac) != 12:
        return None

    return ":".join(raw_mac[index : index + 2] for index in range(0, 12, 2))


def build_unique_id(
    mac_address: str | None,
    model: str | None,
    host: str | None = None,
) -> str:
    """Build a stable unique ID for a cooker."""
    normalized_mac = normalize_mac(mac_address)
    normalized_model = (model or DOMAIN).replace(".", "_")
    if normalized_mac:
        return f"{normalized_model}_{normalized_mac.replace(':', '')}"

    if host:
        normalized_host = host.strip().lower().replace(":", "_").replace(".", "_")
        if normalized_host:
            return f"{normalized_model}_{normalized_host}"

    return f"{normalized_model}_unknown"


def build_entry_title() -> str:
    """Build a config entry title."""
    return DEFAULT_NAME
