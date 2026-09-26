from dataclasses import replace

import pytest
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException

from custom_components.xiaomi_miio_cooker.cmc301 import Cmc301Backend
from custom_components.xiaomi_miio_cooker.select import (
    LidTimeoutSelect,
    PanelRecipeLightsSelect,
    PanelRecipeSelect,
    PanelSleepSelect,
    RecipeTasteSelect,
)


async def test_panel_recipe_lights_write_and_readback(make_coordinator):
    coordinator = make_coordinator()
    lights = PanelRecipeLightsSelect(coordinator, "panel_recipe_lights")
    assert lights.options == ["selected", "all"]
    assert lights.available and lights.current_option == "all"
    for option, flag in (("selected", False), ("all", True)):
        await lights.async_select_option(option)
        coordinator.api.set_setting.assert_called_with("all_modes_lit", flag)
        coordinator.async_set_updated_data(
            replace(
                coordinator.data,
                properties={**coordinator.data.properties, "all_modes_lit": flag},
            )
        )
        assert lights.current_option == option
    coordinator.api.set_setting.reset_mock()
    with pytest.raises(HomeAssistantError):
        await lights.async_select_option("invalid")
    coordinator.api.set_setting.assert_not_called()
    coordinator.async_set_updated_data(replace(coordinator.data, properties={}))
    assert lights.current_option is None and not lights.available
    coordinator.async_set_update_error(DeviceException("Offline"))
    assert not lights.available


async def test_normal3_shared_panel_controls(make_coordinator):
    coordinator = make_coordinator(False)
    coordinator.async_set_updated_data(
        replace(
            coordinator.data,
            properties={
                **coordinator.data.properties,
                "panel_recipe_id": 258,
                "lid_open_timeout": 4,
            },
        )
    )
    recipe = PanelRecipeSelect(coordinator, "panel_recipe")
    sleep = PanelSleepSelect(coordinator, "panel_auto_off")
    lid = LidTimeoutSelect(coordinator, "lid_open_timeout")
    assert recipe.current_option == "refan"
    assert "jingzhu" not in recipe.options and "soup" in recipe.options
    assert sleep.options == ["off", "5", "6", "7", "8", "9", "10"]
    assert lid.current_option == "4" and lid.options == ["2", "4", "6", "8", "10"]
    with pytest.raises(HomeAssistantError):
        await recipe.async_select_option("jingzhu")
    await recipe.async_select_option("soup")
    coordinator.api.set_panel_recipe.assert_called_once()
    coordinator.api.start.assert_not_called()


def test_panel_sleep_atomic_write_and_readback(device, metadata):
    backend = Cmc301Backend(device, metadata)
    device.settings = "0105017f"
    backend.set_setting("panel_sleep", 7)
    assert device.settings == "0007017f"
    writes = [
        p for method, p, _ in device.calls if method == "action" and p["aiid"] == 1
    ]
    assert len(writes) == 1  # Enable and duration travel in one setting string.
    backend.set_setting("panel_sleep", "off")
    assert device.settings == "0107017f"
    device.ignore_writes = True
    with pytest.raises(DeviceException):
        backend.set_setting("panel_sleep", 2)


@pytest.mark.parametrize("value", [1, 11, True, 2.5, "other"])
def test_panel_sleep_rejects_invalid_values_without_io(device, metadata, value):
    with pytest.raises(ValueError):
        Cmc301Backend(device, metadata).set_setting("panel_sleep", value)
    assert not device.calls


def test_panel_feedback_is_distinct_from_current_recipe(device, metadata):
    backend = Cmc301Backend(device, metadata)
    assert backend.fetch_data().properties["panel_recipe_id"] is None
    device.values[2, 3] = 5
    device.values[2, 19] = 3
    assert backend.fetch_data().properties["panel_recipe_id"] == 3
    device.values[2, 3] = 1
    device.values[2, 19] = 1
    assert backend.fetch_data().properties["panel_recipe_id"] == 3
    # A new backend must not treat an ordinary current menu as a saved slot.
    assert (
        Cmc301Backend(device, metadata).fetch_data().properties["panel_recipe_id"]
        is None
    )


async def test_panel_selectors_readback_and_no_other_write(make_coordinator):
    coordinator = make_coordinator()
    sleep = PanelSleepSelect(coordinator, "panel_auto_off")
    panel = PanelRecipeSelect(coordinator, "panel_recipe")
    assert sleep.options == ["off", *map(str, range(2, 11))]
    assert sleep.current_option == "5"
    await sleep.async_select_option("7")
    coordinator.api.set_setting.assert_called_once_with("panel_sleep", 7)
    assert sleep.current_option == "5"  # No optimistic update before readback.
    assert panel.current_option is None and "other" not in panel.options
    coordinator.async_set_updated_data(
        replace(
            coordinator.data,
            properties={**coordinator.data.properties, "panel_recipe_id": 999},
        )
    )
    assert panel.current_option == "other" and "other" in panel.options
    with pytest.raises(HomeAssistantError):
        await panel.async_select_option("other")
    coordinator.api.set_panel_recipe.assert_not_called()
    await panel.async_select_option("zhuzhou")
    coordinator.api.set_panel_recipe.assert_called_once()
    coordinator.api.start.assert_not_called()
    assert coordinator.selected_recipe is None


@pytest.mark.parametrize("cmc", [False, True])
async def test_default_taste_is_a_noop_but_tracks_connection(make_coordinator, cmc):
    coordinator = make_coordinator(cmc)
    taste = RecipeTasteSelect(coordinator, "next_taste")
    for recipe in (None, "kuaizhu", "zhuzhou"):
        if recipe is not None:
            await coordinator.async_select_cooking_menu(recipe)
        assert taste.available and taste.current_option == "default"
        assert taste.options == ["default"]
        await taste.async_select_option("default")
        with pytest.raises(HomeAssistantError):
            await taste.async_select_option("soft")
    coordinator.api.start.assert_not_called()
    coordinator.api.set_setting.assert_not_called()
    await coordinator.async_select_cooking_menu("jingzhu")
    assert "default" not in taste.options
    await taste.async_select_option("soft")
    assert taste.current_option == "soft"
    coordinator.async_set_update_error(DeviceException("Offline"))
    assert not taste.available


@pytest.mark.parametrize("cmc", [False, True])
async def test_custom_candidates_remain_when_running_with_unknown_readback(
    make_coordinator, cmc
):
    coordinator = make_coordinator(cmc)
    selector = PanelRecipeSelect(coordinator, "panel_recipe")
    candidates = selector.options
    assert candidates
    coordinator.async_set_updated_data(
        replace(
            coordinator.data,
            status=replace(coordinator.data.status, status="running"),
            properties={"panel_recipe_id": None},
        )
    )
    assert selector.options == candidates and selector.current_option is None
    assert selector.capability_attributes["options"] == candidates
    assert not selector.available
    with pytest.raises(HomeAssistantError):
        await selector.async_select_option(candidates[0])
    coordinator.api.set_panel_recipe.assert_not_called()
