import asyncio
import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException

from custom_components.xiaomi_miio_cooker import (
    _remove_replaced_duration_number,
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from custom_components.xiaomi_miio_cooker.cmc301 import decode_profile
from custom_components.xiaomi_miio_cooker.const import MODEL_CMC301, MODEL_NORMAL3
from custom_components.xiaomi_miio_cooker.models import CookerStageData
from custom_components.xiaomi_miio_cooker.select import (
    LidTimeoutSelect,
    PanelSleepSelect,
)
from custom_components.xiaomi_miio_cooker.switch import (
    CookerSettingSwitch,
    RecipeKeepWarmSwitch,
)


@pytest.mark.parametrize("cmc", [False, True])
async def test_selectors_show_live_feedback_without_arming_start(
    hass, make_coordinator, cmc
):
    coordinator = make_coordinator(cmc)
    entities = await setup_platforms(hass, coordinator)
    menu, taste, duration = entities["select"][:3]
    start = entities["button"][0]
    assert not start.available
    stage = CookerStageData(None, None, 66, 2, None, None)
    snapshot = replace(
        coordinator.data,
        status=replace(
            coordinator.data.status,
            status="running",
            menu=2 if cmc else 1,
            duration=63,
            stage=stage,
        ),
        properties={**coordinator.data.properties, "texture": 2},
    )
    coordinator.async_set_updated_data(snapshot)
    assert menu.current_option == "jingzhu"
    assert menu.options == ["jingzhu"]
    assert taste.available and taste.current_option == "hard"
    assert taste.options == ["hard"]
    assert duration.available and duration.current_option == "63"
    assert duration.options == ["63"]  # Device value need not lie on the editing grid.
    assert coordinator.selected_recipe is None and not start.available
    for operation in (
        menu.async_select_option("kuaizhu"),
        taste.async_select_option("soft"),
        duration.async_select_option("63"),
        start.async_press(),
    ):
        with pytest.raises(HomeAssistantError):
            await operation
    coordinator.api.start.assert_not_called()
    coordinator.api.set_setting.assert_not_called()
    coordinator.async_set_update_error(DeviceException("Offline"))
    assert not menu.available and not taste.available and not duration.available
    coordinator.async_set_updated_data(
        replace(snapshot, status=replace(snapshot.status, status="idle"))
    )
    assert menu.current_option is None and taste.available and not duration.available
    await menu.async_select_option("jingzhu")
    assert start.available and duration.current_option == "60"


async def setup_platforms(hass, coordinator):
    entities = {}
    for platform in (sensor, select, button, number, switch, binary_sensor):
        result = []
        await platform.async_setup_entry(
            hass,
            coordinator.config_entry,
            lambda items, result=result: result.extend(items),
        )
        entities[platform.__name__.split(".")[-1]] = result
    return entities


async def test_duplicate_start_sent_once(make_coordinator):
    coordinator = make_coordinator()
    await coordinator.async_select_cooking_menu("zhuzhou")
    coordinator.set_recipe_option("duration", 120)
    results = await asyncio.gather(
        coordinator.async_start_selected_profile(),
        coordinator.async_start_selected_profile(),
        return_exceptions=True,
    )
    assert sum(isinstance(result, HomeAssistantError) for result in results) == 1
    coordinator.api.start.assert_called_once()
    data = decode_profile(coordinator.api.start.call_args.args[0])
    assert data[8:10] == bytes([2, 0])
    assert coordinator.selected_recipe is None


async def test_two_cookers_have_independent_selections(make_coordinator):
    first, second = make_coordinator(), make_coordinator()
    await first.async_select_cooking_menu("zhuzhou")
    await second.async_select_cooking_menu("jingzhu")
    first.set_recipe_option("duration", 180)
    assert second.recipe_options.duration == 60
    assert second.selected_cooking_menu == "jingzhu"


async def test_auto_keep_warm_follows_selector_and_connection(hass, make_coordinator):
    coordinator = make_coordinator()
    entities = await setup_platforms(hass, coordinator)
    menu = entities["select"][0]
    warm = next(e for e in entities["switch"] if e.key == "next_auto_keep_warm")
    assert not warm.available and warm.is_on is None
    unsupported = {"baowen", "cake", "noodles", "yoghurt"}
    for recipe in menu.options:
        await menu.async_select_option(recipe)
        assert warm.available == (recipe not in unsupported)
    await menu.async_select_option("kuaizhu")
    await warm.async_turn_off()
    assert warm.available and warm.is_on is False
    coordinator.api.set_setting.assert_not_called()
    coordinator.api.start.assert_not_called()

    previous_data = coordinator.data
    coordinator.async_set_update_error(DeviceException("Offline"))
    assert not menu.available and not warm.available
    coordinator.async_set_updated_data(previous_data)
    assert menu.available and warm.available and warm.is_on is False
    await menu.async_select_option("baowen")
    assert not warm.available
    with pytest.raises(HomeAssistantError, match="unsupported_option"):
        await warm.async_turn_on()
    await menu.async_select_option("kuaizhu")
    assert warm.available and warm.is_on is True
    await coordinator.async_start_selected_profile()
    assert menu.current_option is None
    assert coordinator.recipe_options is None
    assert not warm.available and warm.is_on is None
    sent = decode_profile(coordinator.api.start.call_args.args[0])
    assert int.from_bytes(sent[3:7], "big") == 1
    assert sent[15] & 0x80  # Explicit recipe parameter, not a separate device write.


@pytest.mark.parametrize("cmc", [False, True])
@pytest.mark.parametrize("failure", [False, True])
async def test_shared_selector_reset_preserves_model_error_behavior(
    make_coordinator, cmc, failure
):
    coordinator = make_coordinator(cmc)
    recipe = coordinator.cooking_menu_options[0]
    await coordinator.async_select_cooking_menu(recipe)
    if failure:
        coordinator.api.start.side_effect = DeviceException("Response lost")
        with pytest.raises(HomeAssistantError):
            await coordinator.async_start_selected_profile()
    else:
        await coordinator.async_start_selected_profile()
    expected = recipe if failure and not cmc else None
    assert coordinator.selected_cooking_menu == expected
    assert (coordinator.recipe_options is not None) == (failure and not cmc)


@pytest.mark.parametrize("cmc", [False, True])
@pytest.mark.parametrize("same_recipe", [False, True])
async def test_start_completion_preserves_new_selection(
    make_coordinator, cmc, same_recipe
):
    coordinator = make_coordinator(cmc)
    first, second = coordinator.cooking_menu_options[:2]
    next_recipe = first if same_recipe else second
    await coordinator.async_select_cooking_menu(first)

    async def select_while_starting(*args):
        await coordinator.async_select_cooking_menu(next_recipe)

    coordinator._run_command = AsyncMock(side_effect=select_while_starting)
    await coordinator.async_start_selected_profile()
    assert coordinator.selected_cooking_menu == next_recipe
    assert coordinator.recipe_options is not None


@pytest.mark.parametrize(
    "cmc,reported",
    [(False, False), (False, True), (False, None), (False, 1), (True, None)],
)
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


@pytest.mark.parametrize("state", ["running", "keep_warm", "unknown"])
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
