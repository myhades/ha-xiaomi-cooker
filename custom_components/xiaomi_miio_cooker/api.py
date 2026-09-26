"""Model dispatch and serialized blocking device access."""

from __future__ import annotations

import re
from threading import RLock
from typing import Any

from miio import Device, DeviceException

from .const import MODEL_CMC301, SUPPORTED_MODELS
from .contracts import CookerBackend, PanelRecipeBackend, SettingsBackend
from .models import (  # Stable imports used by the HA layer.
    CookerData,
    CookerDeviceMetadata,
    normalize_mac,
)
from .models import (
    build_entry_title as build_entry_title,
)
from .models import (
    build_unique_id as build_unique_id,
)
from .recipe_options import ScheduledRecipe


class UnsupportedModelError(Exception):
    """The discovered device has no compatible backend."""


def normalize_token(value: str) -> str:
    """Accept Windows whitespace/BOM without including secrets in errors."""
    token = "".join(value.replace("\ufeff", "").split())
    if not re.fullmatch(r"[0-9a-fA-F]{32}", token):
        raise ValueError("Token must be 32 hexadecimal characters")
    return token.lower()


class XiaomiMiioCookerApi:
    """One facade, separate protocols, one lock for polling and commands."""

    def __init__(self, host: str, token: str, model: str | None) -> None:
        self.host = host
        self.token = normalize_token(token)
        self.configured_model = model
        self._device = Device(host, self.token)
        self._device_info: CookerDeviceMetadata | None = None
        self._backend: CookerBackend | None = None
        self._lock = RLock()

    def validate(self) -> CookerData:
        return self.fetch_data(force_device_info=True)

    def fetch_device_info(self) -> CookerDeviceMetadata:
        with self._lock:
            return self._get_device_info(True)

    def _get_device_info(self, force: bool = False) -> CookerDeviceMetadata:
        if self._device_info is None or force:
            info = self._device.info()
            if info is None:
                raise DeviceException("No device information returned")
            self._device_info = CookerDeviceMetadata(
                model=getattr(info, "model", None),
                firmware_version=getattr(info, "firmware_version", None),
                hardware_version=getattr(info, "hardware_version", None),
                mac_address=normalize_mac(
                    getattr(info, "mac_address", None) or getattr(info, "mac", None)
                ),
            )
        return self._device_info

    def _get_backend(self) -> CookerBackend:
        metadata = self._get_device_info()
        model = metadata.model
        if model not in SUPPORTED_MODELS:
            raise UnsupportedModelError(f"Unsupported device: {model}")
        if self.configured_model is not None and self.configured_model != model:
            raise UnsupportedModelError(
                "Configured and discovered cooker models differ"
            )
        if self._backend is None:
            if model == MODEL_CMC301:
                from .cmc301 import Cmc301Backend

                self._backend = Cmc301Backend(self._device, metadata)
            else:
                from .normal3 import Normal3Backend

                self._backend = Normal3Backend(self.host, self.token, metadata)
        return self._backend

    def fetch_data(
        self, force_device_info: bool = False, *, core_only: bool = False
    ) -> CookerData:
        with self._lock:
            self._get_device_info(force_device_info)
            backend = self._get_backend()
            if core_only and self._device_info.model == MODEL_CMC301:
                from .cmc301 import Cmc301Backend

                assert isinstance(backend, Cmc301Backend)
                return backend.fetch_core_data()
            return backend.fetch_data()

    def fetch_detail(self, snapshot: CookerData, kind: str) -> CookerData:
        """Release the device lock between optional reads so controls can run."""
        from .cmc301 import Cmc301Backend

        with self._lock:
            backend = self._get_backend()
            if not isinstance(backend, Cmc301Backend):
                raise ValueError("Split detail reads are only supported on CMC301")
            return backend.fetch_detail(snapshot, kind)

    def validate_profile(self, profile: str) -> None:
        """Preflight all service targets before any start is sent."""
        model = self.configured_model or (
            self._device_info.model if self._device_info else None
        )
        if model == MODEL_CMC301:
            from .cmc301 import validate_bundled_profile

            validate_bundled_profile(profile)
        elif len(profile) == 352:
            raise ValueError("A CMC301 recipe cannot be sent to a legacy cooker")

    def start(self, profile: str | ScheduledRecipe) -> Any:
        with self._lock:
            backend = self._get_backend()
            if isinstance(profile, ScheduledRecipe):
                from .normal3 import Normal3Backend

                if not isinstance(backend, Normal3Backend):
                    raise ValueError("Clock-based schedules require normal3")
                return backend.start_scheduled(profile)
            self.validate_profile(profile)
            return backend.start(profile)

    def stop(self) -> Any:
        with self._lock:
            return self._get_backend().stop()

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            backend = self._get_backend()
            if not isinstance(backend, SettingsBackend):
                raise ValueError("Settings control is not supported by this backend")
            backend.set_setting(key, value)

    def set_panel_recipe(self, profile: str) -> None:
        with self._lock:
            backend = self._get_backend()
            if not isinstance(backend, PanelRecipeBackend):
                raise ValueError(
                    "Panel recipe control is not supported by this backend"
                )
            backend.set_panel_recipe(profile)
