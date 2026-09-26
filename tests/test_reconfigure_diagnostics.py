"""Identity-preserving reconfiguration and private, offline diagnostics."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import UNDEFINED
from miio import DeviceException

from custom_components.xiaomi_miio_cooker import config_flow
from custom_components.xiaomi_miio_cooker.const import DOMAIN, MODEL_CMC301
from custom_components.xiaomi_miio_cooker.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.xiaomi_miio_cooker.exceptions import CookerCommandError


@pytest.fixture
def flow_context(hass, monkeypatch):
    entry = SimpleNamespace(
        entry_id="private-entry",
        unique_id="private-identity",
        update_listeners=[],
        data={"host": "192.0.2.1", "token": "a" * 32, "model": MODEL_CMC301},
    )
    manager = SimpleNamespace(
        async_get_known_entry=Mock(return_value=entry),
        async_entry_for_domain_unique_id=Mock(return_value=entry),
        async_update_entry=Mock(return_value=True),
        async_schedule_reload=Mock(),
        flow=SimpleNamespace(async_progress_by_handler=Mock(return_value=[])),
    )
    hass.config_entries = manager
    flow = config_flow.XiaomiMiioCookerConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    validate = AsyncMock(
        return_value={
            "unique_id": entry.unique_id,
            "model": MODEL_CMC301,
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "title": "Rice cooker",
        }
    )
    monkeypatch.setattr(config_flow, "_async_validate_input", validate)
    return flow, entry, manager, validate


async def test_reconfigure_form_never_prefills_token(flow_context):
    flow, entry, _, _ = flow_context
    result = await flow.async_step_reconfigure()
    schema = result["data_schema"]
    assert schema({"host": "192.0.2.2"}) == {"host": "192.0.2.2"}
    assert entry.data["token"] not in str(result)


@pytest.mark.parametrize(
    "token", [None, "", " \r\n\ufeff", "\ufeff" + "B" * 32 + "\r\n"]
)
async def test_reconfigure_preserves_identity_and_reloads_once(flow_context, token):
    flow, entry, manager, validate = flow_context
    user_input = {"host": " 192.0.2.2 "}
    if token is not None:
        user_input["token"] = token
    result = await flow.async_step_reconfigure(user_input)
    assert result["reason"] == "reconfigure_successful"
    expected = "b" * 32 if token and "B" in token else "a" * 32
    assert validate.call_args.args[1]["token"] == expected
    manager.async_update_entry.assert_called_once()
    args = manager.async_update_entry.call_args.kwargs
    assert args["data"] == {
        "host": "192.0.2.2",
        "token": expected,
        "model": MODEL_CMC301,
    }
    assert args["unique_id"] is UNDEFINED
    manager.async_schedule_reload.assert_called_once_with(entry.entry_id)
    assert entry.unique_id == "private-identity"


async def test_reconfigure_rejects_different_device(flow_context):
    flow, _, manager, validate = flow_context
    validate.return_value["unique_id"] = "other-cooker"
    with pytest.raises(AbortFlow) as error:
        await flow.async_step_reconfigure({"host": "192.0.2.2"})
    assert error.value.reason == "wrong_device"
    manager.async_update_entry.assert_not_called()
    manager.async_schedule_reload.assert_not_called()


@pytest.mark.parametrize(
    "failure, expected",
    [
        (config_flow.CannotConnect(), "cannot_connect"),
        (config_flow.CannotDetectModel(), "cannot_detect_model"),
        (config_flow.UnsupportedModelError(), "unsupported_model"),
    ],
)
async def test_reconfigure_failure_preserves_connection(
    flow_context, failure, expected
):
    flow, entry, manager, validate = flow_context
    validate.side_effect = failure
    result = await flow.async_step_reconfigure({"host": "192.0.2.2"})
    assert result["errors"] == {"base": expected}
    assert entry.data["host"] == "192.0.2.1"
    assert entry.data["token"] not in str(result)
    manager.async_update_entry.assert_not_called()
    manager.async_schedule_reload.assert_not_called()


async def test_reconfigure_missing_identity_does_not_save(flow_context):
    flow, _, manager, validate = flow_context
    validate.return_value["mac_address"] = None
    result = await flow.async_step_reconfigure({"host": "192.0.2.2"})
    assert result["errors"] == {"base": "cannot_verify_identity"}
    manager.async_update_entry.assert_not_called()


async def test_reconfigure_invalid_token_is_never_sent(flow_context):
    flow, _, manager, validate = flow_context
    result = await flow.async_step_reconfigure(
        {"host": "192.0.2.2", "token": "secret-bad-token"}
    )
    assert result["errors"] == {"base": "invalid_token"}
    assert "secret-bad-token" not in str(result)
    validate.assert_not_called()
    manager.async_update_entry.assert_not_called()


@pytest.mark.parametrize("cmc", [True, False])
async def test_diagnostics_exclude_secrets_and_never_poll(
    hass, make_coordinator, cmc, caplog
):
    coordinator = make_coordinator(cmc)
    await coordinator.async_select_cooking_menu("jingzhu")
    entry = coordinator.config_entry
    entry.data.update(
        token="private-token", host="private-host", private="private-field"
    )
    entry.unique_id = "private-unique"
    coordinator.last_exception = DeviceException("private-exception-with-token")
    coordinator.data = replace(
        coordinator.data,
        device_info=replace(coordinator.data.device_info, mac_address="private-mac"),
        properties={
            **coordinator.data.properties,
            "token": "private-token",
            "unknown": "private-field",
            "reset_flag": 2,
            "recipe_type": 0,
        },
    )
    coordinator.api.reset_mock()
    result = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(result)
    assert "private-" not in dumped
    assert result["selected_recipe"] == "jingzhu"
    assert result["last_exception_type"] == "DeviceException"
    assert result["recipe_options"]["duration"] > 0
    assert "status" in result and "firmware_version" in result["device"]
    assert coordinator.api.mock_calls == []
    coordinator.async_refresh.assert_not_awaited()
    assert result["properties"]["reset_flag"] == 2
    assert result["properties"]["recipe_type"] == 0
    coordinator.api.fetch_data.return_value = coordinator.data
    with caplog.at_level(
        "DEBUG", logger="custom_components.xiaomi_miio_cooker.coordinator"
    ):
        await coordinator._async_update_data()
    assert "protocol diagnostics" in caplog.text and "reset_flag" in caplog.text
    assert "private-" not in caplog.text


async def test_command_error_uses_translation_key_without_raw_reply(make_coordinator):
    coordinator = make_coordinator()
    coordinator.api.stop.side_effect = CookerCommandError(
        "write_unconfirmed", "private-raw-reply"
    )
    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_stop()
    assert caught.value.translation_key == "write_unconfirmed"
    assert caught.value.translation_domain == DOMAIN
    assert "private-raw-reply" not in str(caught.value)


async def test_recipe_error_has_translated_range(make_coordinator):
    coordinator = make_coordinator()
    with pytest.raises(HomeAssistantError) as caught:
        coordinator.prepare_recipe("kuaizhu", {"duration": 99})
    assert caught.value.translation_key == "duration_out_of_range"
    assert caught.value.translation_placeholders == {"minimum": "28", "maximum": "28"}


@pytest.mark.parametrize(
    "model",
    ["xiaomi.cooker.cmc301", "chunmi.cooker.normal3", "chunmi.cooker.normal4", None],
)
async def test_detection_uses_device_identity_and_rejects_other_models(
    hass, monkeypatch, model
):
    api = Mock()
    api.fetch_device_info.return_value = SimpleNamespace(
        model=model, mac_address="aa:bb:cc:dd:ee:ff"
    )
    factory = Mock(return_value=api)
    monkeypatch.setattr(config_flow, "XiaomiMiioCookerApi", factory)
    data = {"host": "192.0.2.1", "token": "a" * 32, "model": "xiaomi.cooker.cmc301"}
    if model in ("xiaomi.cooker.cmc301", "chunmi.cooker.normal3"):
        result = await config_flow._async_validate_input(hass, data)
        assert result["model"] == model
        api.fetch_data.assert_called_once()
    else:
        error = (
            config_flow.CannotDetectModel
            if model is None
            else config_flow.UnsupportedModelError
        )
        with pytest.raises(error):
            await config_flow._async_validate_input(hass, data)
        api.fetch_data.assert_not_called()
    assert factory.call_args.kwargs["model"] is None


def test_setup_schema_has_only_connection_fields():
    schema = config_flow.XiaomiMiioCookerConfigFlow._build_schema()
    assert {str(key) for key in schema.schema} == {"host", "token"}
