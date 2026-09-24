import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException

from custom_components.xiaomi_miio_cooker import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from custom_components.xiaomi_miio_cooker.cmc301_profile import decode_profile


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


async def test_legacy_entities_unchanged(hass, make_coordinator):
    coordinator = make_coordinator(False)
    entities = await setup_platforms(hass, coordinator)
    assert len(entities["sensor"]) == 15
    assert len(entities["select"]) == 3
    assert len(entities["button"]) == 2
    assert entities["number"] == entities["binary_sensor"] == []
    assert [e.key for e in entities["switch"]] == ["next_auto_keep_warm"]
    for entity in entities["sensor"]:
        assert (
            entity.unique_id
            == coordinator.device_unique_id + "_" + entity.entity_description.key
        )
    assert entities["sensor"][0].options == list(sensor.MODE_OPTIONS)
    assert entities["sensor"][1].options == list(sensor.STATUS_OPTIONS)


async def test_cmc_menu_units_options_and_independent_draft(hass, make_coordinator):
    coordinator = make_coordinator()
    entities = await setup_platforms(hass, coordinator)
    sensors = {entity.entity_description.key: entity for entity in entities["sensor"]}
    assert sensors["menu"].native_value == "kuaizhu"
    assert sensors["remaining"].native_value == 61 / 60
    assert "lid_open_warning" not in sensors
    assert "rice_id" not in sensors
    assert sensors["recorded_temperature"].native_value == 27
    assert sensors["texture"].native_value == "middle"
    await coordinator.async_select_cooking_menu("jingzhu")
    coordinator.set_recipe_option("taste", 2)
    assert sensors["texture"].native_value == "middle"
    assert coordinator.recipe_options.taste == 2
    await coordinator.async_select_cooking_menu("zhuzhou")
    assert not coordinator.supports_option("taste")
    assert coordinator.supports_option("duration")
    with pytest.raises(HomeAssistantError):
        coordinator.set_recipe_option("taste", 2)
    duration = next(
        e for e in entities["select"] if getattr(e, "key", None) == "next_duration"
    )
    assert duration.options == [str(value) for value in range(40, 241, 10)]
    await duration.async_select_option("120")
    assert coordinator.recipe_options.duration == 120
    await coordinator.async_select_cooking_menu("kuaizhu")
    assert coordinator.recipe_options.duration == 28
    assert duration.available and duration.options == ["28"]
    assert duration.current_option == "28"


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


async def test_failed_start_refreshes_and_disarms_draft(make_coordinator):
    coordinator = make_coordinator()
    coordinator.api.start.side_effect = DeviceException("Start was not confirmed")
    await coordinator.async_select_cooking_menu("kuaizhu")
    with pytest.raises(HomeAssistantError, match="command_failed"):
        await coordinator.async_start_selected_profile()
    coordinator.async_refresh.assert_awaited_once()
    assert coordinator.selected_recipe is None
    coordinator._cancel_delayed_refresh()
    assert coordinator._refresh_task is None


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


@pytest.mark.parametrize("cmc", [False, True])
async def test_recreated_coordinator_starts_without_a_selection(make_coordinator, cmc):
    previous = make_coordinator(cmc)
    await previous.async_select_cooking_menu(previous.cooking_menu_options[0])
    current = make_coordinator(cmc)
    assert current.selected_cooking_menu is None
    assert current.recipe_options is None
    assert not current.supports_option("auto_keep_warm")
