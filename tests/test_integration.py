from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException

from custom_components import xiaomi_miio_cooker as integration
from custom_components.xiaomi_miio_cooker import services
from custom_components.xiaomi_miio_cooker.api import XiaomiMiioCookerApi
from custom_components.xiaomi_miio_cooker.cmc301 import decode_profile
from custom_components.xiaomi_miio_cooker.config_flow import (
    CannotConnect,
    _async_validate_input,
)
from custom_components.xiaomi_miio_cooker.const import (
    DOMAIN,
    MODEL_CMC301,
    MODEL_NORMAL3,
)
from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model
from custom_components.xiaomi_miio_cooker.services import async_register_services


async def test_atomic_recipe_service(hass, make_coordinator):
    coordinator = make_coordinator()
    await async_register_services(hass)
    await hass.services.async_call(
        DOMAIN,
        "start_recipe",
        {
            "recipe": "zhuzhou",
            "duration": 120,
            "finish_in": 500,
            "auto_keep_warm": False,
        },
        blocking=True,
    )
    coordinator.api.start.assert_called_once()
    data = decode_profile(coordinator.api.start.call_args.args[0])
    assert data[8:10] == bytes([2, 0])
    assert data[14:16] == bytes([0x88, 20])
    assert coordinator.selected_recipe is None


async def test_invalid_recipe_service_has_no_device_effect(hass, make_coordinator):
    coordinator = make_coordinator()
    await async_register_services(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "start_recipe", {"recipe": "kuaizhu", "duration": 90}, blocking=True
        )
    coordinator.api.start.assert_not_called()


async def test_mixed_raw_service_preflights_before_start(
    hass, make_coordinator, monkeypatch
):
    from custom_components.xiaomi_miio_cooker import services as integration

    first, second = make_coordinator(), make_coordinator(False)
    for coordinator, model in ((first, MODEL_CMC301), (second, MODEL_NORMAL3)):
        coordinator.api.validate_profile = XiaomiMiioCookerApi(
            "192.0.2.1", "0" * 32, model
        ).validate_profile
    monkeypatch.setattr(
        integration, "_async_resolve_coordinators", lambda *_: [first, second]
    )
    await async_register_services(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "start",
            {"profile": get_profiles_for_model(MODEL_CMC301)[0].profile},
            blocking=True,
        )
    first.api.start.assert_not_called()
    second.api.start.assert_not_called()


async def test_config_validation_surfaces_connection_failure(hass, monkeypatch, caplog):
    api = Mock()
    token = "abcdef0123456789abcdef0123456789"
    api.fetch_device_info.side_effect = DeviceException(f"No response; token={token}")
    monkeypatch.setattr(
        "custom_components.xiaomi_miio_cooker.config_flow.XiaomiMiioCookerApi",
        Mock(return_value=api),
    )
    with pytest.raises(CannotConnect):
        await _async_validate_input(
            hass, {"host": "192.0.2.1", "token": token, "model": "auto"}
        )
    assert "miIO.info" in caplog.text
    assert "No response" in caplog.text
    assert token not in caplog.text
    assert "[redacted]" in caplog.text


def test_poll_and_command_share_one_lock(metadata):
    api = XiaomiMiioCookerApi("192.0.2.1", "0" * 32, MODEL_CMC301)
    api._device_info = metadata
    entered, release, command_attempted = Event(), Event(), Event()

    def fetch():
        entered.set()
        assert release.wait(5)

    api._backend = Mock()
    api._backend.fetch_data.side_effect = fetch

    def stop():
        command_attempted.set()
        api.stop()

    with ThreadPoolExecutor(max_workers=2) as executor:
        poll = executor.submit(api.fetch_data)
        assert entered.wait(5)
        command = executor.submit(stop)
        assert command_attempted.wait(5)
        api._backend.stop.assert_not_called()
        release.set()
        poll.result(5)
        command.result(5)
    api._backend.stop.assert_called_once()


async def test_actions_exist_without_loaded_entries(hass, make_coordinator):
    assert await integration.async_setup(hass, {})
    for service in ("start", "start_recipe"):
        assert hass.services.has_service(DOMAIN, service)
    with pytest.raises(HomeAssistantError, match="no_loaded_device"):
        await hass.services.async_call(
            DOMAIN, "start_recipe", {"recipe": "kuaizhu"}, blocking=True
        )
    coordinator = make_coordinator()
    coordinator.config_entry.state = ConfigEntryState.SETUP_RETRY
    with pytest.raises(HomeAssistantError, match="no_loaded_device"):
        await hass.services.async_call(
            DOMAIN, "start_recipe", {"recipe": "kuaizhu"}, blocking=True
        )
    coordinator.api.start.assert_not_called()


@pytest.mark.parametrize("unload_ok", [True, False])
async def test_unload_does_not_unregister_actions(hass, make_coordinator, unload_ok):
    coordinator = make_coordinator()
    await integration.async_setup(hass, {})
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=unload_ok)
    assert (
        await integration.async_unload_entry(hass, coordinator.config_entry)
        is unload_ok
    )
    assert hass.services.has_service(DOMAIN, "start_recipe")
    assert DOMAIN not in hass.data


@pytest.mark.parametrize("registry_api", ["single", "composite"])
async def test_device_targets_resolve_once_without_deprecated_reads(
    hass, make_coordinator, monkeypatch, registry_api
):
    coordinator = make_coordinator()
    entry = coordinator.config_entry

    class SingleDevice:
        config_entry_id = entry.entry_id
        is_composite_device = False

        @property
        def config_entries(self):
            raise AssertionError("Modern devices must not read the deprecated property")

    device = SingleDevice()
    registry = SimpleNamespace(
        async_get=lambda _: device,
        async_get_devices_for_composite_device_id=lambda _: (
            [device] if registry_api == "composite" else []
        ),
    )
    monkeypatch.setattr(services.dr, "async_get", lambda _: registry)
    await integration.async_setup(hass, {})
    await hass.services.async_call(
        DOMAIN,
        "start_recipe",
        {"device_id": ["stored-id", "stored-id"], "recipe": "kuaizhu"},
        blocking=True,
    )
    coordinator.api.start.assert_called_once()


@pytest.mark.parametrize("target", ["missing", "foreign", "unloaded"])
async def test_invalid_second_target_prevents_all_starts(
    hass, make_coordinator, monkeypatch, target
):
    first, second = make_coordinator(), make_coordinator(False)
    second.config_entry.state = ConfigEntryState.NOT_LOADED
    valid = SimpleNamespace(config_entry_id=first.config_entry.entry_id)
    bad = {
        "missing": None,
        "foreign": SimpleNamespace(config_entry_id="other"),
        "unloaded": SimpleNamespace(config_entry_id=second.config_entry.entry_id),
    }[target]
    registry = SimpleNamespace(
        async_get=lambda device_id: valid if device_id == "valid" else bad,
        async_get_devices_for_composite_device_id=lambda _: [],
    )
    monkeypatch.setattr(services.dr, "async_get", lambda _: registry)
    await integration.async_setup(hass, {})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "start_recipe",
            {"device_id": ["valid", "bad"], "recipe": "kuaizhu"},
            blocking=True,
        )
    first.api.start.assert_not_called()
    second.api.start.assert_not_called()


async def test_service_follows_reloaded_runtime_data(hass, make_coordinator):
    old = make_coordinator()
    await integration.async_setup(hass, {})
    old.config_entry.state = ConfigEntryState.NOT_LOADED
    new = make_coordinator()
    await hass.services.async_call(
        DOMAIN, "start_recipe", {"recipe": "kuaizhu"}, blocking=True
    )
    old.api.start.assert_not_called()
    new.api.start.assert_called_once()


async def test_setup_publishes_runtime_before_platforms(
    hass, make_coordinator, monkeypatch
):
    coordinator = make_coordinator()
    entry = coordinator.config_entry
    del entry.runtime_data
    entry.data["token"] = "0" * 32
    entry.add_update_listener = Mock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    monkeypatch.setattr(integration, "XiaomiMiioCookerApi", Mock())
    monkeypatch.setattr(
        integration, "XiaomiMiioCookerCoordinator", Mock(return_value=coordinator)
    )
    monkeypatch.setattr(integration, "_remove_replaced_duration_number", Mock())

    async def forward(forwarded_entry, platforms):
        assert forwarded_entry.runtime_data is coordinator
        assert DOMAIN not in hass.data

    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=forward)
    hass.config_entries.async_update_entry = Mock()
    assert await integration.async_setup_entry(hass, entry)
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


async def test_failed_first_refresh_has_no_runtime(hass, make_coordinator, monkeypatch):
    coordinator = make_coordinator()
    entry = coordinator.config_entry
    del entry.runtime_data
    entry.data["token"] = "0" * 32
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=HomeAssistantError("offline")
    )
    monkeypatch.setattr(integration, "XiaomiMiioCookerApi", Mock())
    monkeypatch.setattr(
        integration, "XiaomiMiioCookerCoordinator", Mock(return_value=coordinator)
    )
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    with pytest.raises(HomeAssistantError, match="offline"):
        await integration.async_setup_entry(hass, entry)
    assert not hasattr(entry, "runtime_data")
    hass.config_entries.async_forward_entry_setups.assert_not_awaited()
