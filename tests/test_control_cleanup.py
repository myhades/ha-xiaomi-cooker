"""Shared control feedback, write guards and translation consistency."""

import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException

from custom_components.xiaomi_miio_cooker import _remove_replaced_duration_number
from custom_components.xiaomi_miio_cooker.const import MODEL_CMC301, MODEL_NORMAL3
from custom_components.xiaomi_miio_cooker.select import (
    LidTimeoutSelect,
    PanelSleepSelect,
)
from custom_components.xiaomi_miio_cooker.switch import (
    CookerSettingSwitch,
    RecipeKeepWarmSwitch,
)


@pytest.mark.parametrize("cmc", [False, True])
@pytest.mark.parametrize("reported", [False, True, None, 1])
async def test_keep_warm_live_feedback_never_uses_draft(
    make_coordinator, cmc, reported
):
    c = make_coordinator(cmc)
    await c.async_select_cooking_menu("jingzhu")
    warm = RecipeKeepWarmSwitch(c, "next_auto_keep_warm")
    c.async_set_updated_data(
        replace(
            c.data,
            status=replace(c.data.status, status="running"),
            properties={"auto_keep_warm": reported},
        )
    )
    assert warm.is_on is (reported if type(reported) is bool else None)
    assert warm.available == (type(reported) is bool)
    assert warm.extra_state_attributes == {"read_only": True}
    for action in (warm.async_turn_on, warm.async_turn_off):
        with pytest.raises(HomeAssistantError):
            await action()
    c.api.set_setting.assert_not_called()
    c.async_set_update_error(DeviceException("offline"))
    assert not warm.available


@pytest.mark.parametrize(
    "state", ["running", "scheduled", "keep_warm", "busy", "unknown"]
)
async def test_normal3_settings_disabled_before_command(make_coordinator, state):
    c = make_coordinator(False)
    snapshot = replace(
        c.data,
        properties={
            "panel_auto_off": True,
            "display_timeout": 5,
            "lid_open_timeout": 4,
            "completion_notification": False,
        },
    )
    c.async_set_updated_data(snapshot)
    controls = [
        PanelSleepSelect(c, "panel_auto_off"),
        LidTimeoutSelect(c, "lid_open_timeout"),
        CookerSettingSwitch(c, "completion_notification"),
    ]
    assert all(e.available for e in controls)
    c.async_set_updated_data(
        replace(snapshot, status=replace(snapshot.status, status=state))
    )
    assert all(not e.available for e in controls)
    with pytest.raises(HomeAssistantError):
        await c.async_set_setting("completion_notification", True)
    c.api.set_setting.assert_not_called()
    c.async_set_updated_data(snapshot)
    assert all(e.available for e in controls)


@pytest.mark.parametrize("model", [MODEL_CMC301, MODEL_NORMAL3])
@pytest.mark.parametrize("same_entry", [False, True])
async def test_stage_migration_preserves_name_and_other_entries(
    hass, monkeypatch, model, same_entry
):
    registry = Mock()
    registry.async_get_entity_id.side_effect = lambda domain, platform, uid: (
        "sensor.old_description" if uid == "device_stage_description" else None
    )
    registry.async_get.return_value = SimpleNamespace(
        config_entry_id="ours" if same_entry else "other"
    )
    monkeypatch.setattr(
        "custom_components.xiaomi_miio_cooker.er.async_get", lambda _: registry
    )
    _remove_replaced_duration_number(
        hass, SimpleNamespace(entry_id="ours"), "device", model
    )
    assert registry.async_remove.call_count == int(same_entry)
    assert all(
        call.args[2] != "device_stage_name"
        for call in registry.async_get_entity_id.call_args_list
    )


def test_translations_have_matching_keys_and_placeholders():
    root = Path(__file__).parents[1] / "custom_components/xiaomi_miio_cooker"

    def leaves(value, prefix=""):
        result = {}
        for key, item in value.items():
            path = f"{prefix}.{key}"
            result.update(
                leaves(item, path) if isinstance(item, dict) else {path: item}
            )
        return result

    source = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    base = leaves(source)
    for language in ("en", "zh-Hans", "de"):
        translated = json.loads(
            (root / f"translations/{language}.json").read_text(encoding="utf-8")
        )
        actual = leaves(translated)
        assert actual.keys() == base.keys()
        assert all(isinstance(text, str) and text.strip() for text in actual.values())
        for key in base:
            assert re.findall(r"\{[^}]+\}", base[key]) == re.findall(
                r"\{[^}]+\}", actual[key]
            )
        if language == "en":
            assert translated == source
