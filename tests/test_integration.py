from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException

from custom_components.xiaomi_miio_cooker.api import XiaomiMiioCookerApi
from custom_components.xiaomi_miio_cooker.cmc301_profile import decode_profile
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
