"""Tests use real HA classes and fake device transports. No network allowed."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from miio import Device, DeviceException

from custom_components.xiaomi_miio_cooker.const import MODEL_CMC301, MODEL_NORMAL3
from custom_components.xiaomi_miio_cooker.models import CookerDeviceMetadata


@pytest.fixture(autouse=True)
def no_device_network(monkeypatch):
    monkeypatch.setattr(
        Device,
        "send",
        Mock(side_effect=AssertionError("Real device I/O forbidden in tests")),
    )
    monkeypatch.setattr(
        Device,
        "info",
        Mock(side_effect=AssertionError("Real discovery forbidden in tests")),
    )


@pytest.fixture
def metadata():
    return CookerDeviceMetadata(MODEL_CMC301, "1.1.3", "ESP32C3", "aa:bb:cc:dd:ee:ff")


class FakeDevice:
    def __init__(self):
        self.values = {
            (2, 1): 1,
            (2, 2): 0,
            (2, 3): 1,
            (2, 19): 1,
            (2, 20): 28,
            (2, 21): 61,
            (2, 26): 1,
            (2, 29): False,
            (2, 30): 0,
            (2, 31): 2,
            (2, 32): False,
            (7, 1): True,
            (2, 28): "00021a1baa",
        }
        self.settings = "00050101"
        self.calls = []
        self.fail_properties = set()
        self.fail_actions = set()
        self.timeout_start = False
        self.ignore_writes = False

    def send(self, method, params, retry_count=None):
        self.calls.append((method, deepcopy(params), retry_count))
        if method == "get_properties":
            return [
                dict(
                    item,
                    code=-4001
                    if (item["siid"], item["piid"]) in self.fail_properties
                    else 0,
                    value=self.values.get((item["siid"], item["piid"])),
                )
                for item in reversed(params)
            ]
        if method == "set_properties":
            for item in params:
                if not self.ignore_writes:
                    self.values[item["siid"], item["piid"]] = item["value"]
            return [dict(item, code=0) for item in params]
        if method == "action":
            action = params["siid"], params["aiid"]
            if action in self.fail_actions:
                return {"code": -4001}
            if action == (2, 6) and self.timeout_start:
                raise DeviceException("Response lost")
            if action == (6, 2):
                return {"code": 0, "out": [{"piid": 1, "value": self.settings}]}
            if action == (6, 1) and not self.ignore_writes:
                self.settings = params["in"][0]["value"]
            return {"code": 0, "out": []}
        raise AssertionError(method)


@pytest.fixture
def device():
    return FakeDevice()


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    yield instance
    await instance.async_stop(force=True)


@pytest.fixture
def make_coordinator(hass, metadata):
    from custom_components.xiaomi_miio_cooker.cmc301 import Cmc301Backend
    from custom_components.xiaomi_miio_cooker.coordinator import (
        XiaomiMiioCookerCoordinator,
    )
    from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model

    coordinators = []
    hass.config_entries = SimpleNamespace(
        async_entries=lambda domain: [c.config_entry for c in coordinators]
    )

    def make(cmc=True, *, model=None):
        model = model or (MODEL_CMC301 if cmc else MODEL_NORMAL3)
        entry = SimpleNamespace(
            data={"model": model, "host": "192.0.2.1"},
            entry_id=model,
            unique_id=model + "_aabbccddeeff",
            async_on_unload=Mock(),
            pref_disable_polling=False,
            state=ConfigEntryState.LOADED,
        )
        api = Mock()
        coordinator = XiaomiMiioCookerCoordinator(
            hass, entry, api, get_profiles_for_model(model)
        )
        entry.runtime_data = coordinator
        coordinator.async_refresh = AsyncMock()
        coordinator.async_set_updated_data(
            Cmc301Backend(FakeDevice(), metadata).fetch_data()
        )
        coordinators.append(coordinator)
        return coordinator

    yield make
    for coordinator in coordinators:
        coordinator._cancel_delayed_refresh()
