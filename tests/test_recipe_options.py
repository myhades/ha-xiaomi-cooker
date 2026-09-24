"""Recipe headers, controls and migration without any hardware I/O."""

from binascii import crc_hqx
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from miio import DeviceException
from test_entities import setup_platforms

from custom_components.xiaomi_miio_cooker import (
    _remove_replaced_duration_number,
)
from custom_components.xiaomi_miio_cooker import (
    normal3_profile as codec,
)
from custom_components.xiaomi_miio_cooker.const import MODEL_NORMAL3, MODEL_NORMAL4
from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model
from custom_components.xiaomi_miio_cooker.recipe_options import duration_choices

RECIPES = {r.key: r.profile for r in get_profiles_for_model(MODEL_NORMAL3)}


@pytest.mark.parametrize("key", RECIPES)
def test_normal3_default_roundtrip_and_range(key):
    profile = RECIPES[key]
    defaults = codec.default_options(profile)
    assert codec.encode_profile(profile, defaults) == profile
    minimum, maximum = codec.duration_range(profile)
    assert minimum <= defaults.duration <= maximum
    choices = duration_choices(minimum, maximum, defaults.duration)
    assert choices[0] == minimum and choices[-1] == maximum
    assert defaults.duration in choices
    for duration in (minimum, maximum):
        result = codec.decode_profile(
            codec.encode_profile(profile, replace(defaults, duration=duration))
        )
        assert result[3:5] == bytes(divmod(duration, 60))
        assert result[11:-2] == bytes.fromhex(profile)[11:-2]


def test_normal3_taste_does_not_change_time_bounds_or_program():
    profile = RECIPES["jingzhu"]
    result = codec.encode_profile(
        profile, replace(codec.default_options(profile), taste=2, auto_keep_warm=False)
    )
    raw = codec.decode_profile(result)
    assert raw[7] == 2 and raw[10] & 0x80 == 0
    assert codec.duration_range(result) == (60, 60)
    original = bytes.fromhex(profile)
    assert {
        i
        for i, (a, b) in enumerate(zip(original[:-2], raw[:-2], strict=True))
        if a != b
    } == {
        7,
        10,
    }
    assert crc_hqx(raw[:-2], 0) == int.from_bytes(raw[-2:], "big")
    # The same byte stores minimum hours in other menus, not their taste.
    yoghurt = RECIPES["yoghurt"]
    edited = codec.decode_profile(
        codec.encode_profile(
            yoghurt, replace(codec.default_options(yoghurt), duration=600)
        )
    )
    assert edited[7] == 6


@pytest.mark.parametrize(
    "key,changes",
    [
        ("jingzhu", {"duration": 70}),
        ("kuaizhu", {"taste": 1}),
        ("zhuzhou", {"duration": 39}),
        ("zhuzhou", {"duration": 241}),
        ("zhuzhou", {"duration": True}),
        ("baowen", {"auto_keep_warm": True}),
        ("jingzhu", {"taste": True}),
        ("jingzhu", {"taste": 3}),
        ("jingzhu", {"finish_in": 120}),
    ],
)
def test_normal3_rejects_invalid_parameter_edits(key, changes):
    profile = RECIPES[key]
    with pytest.raises(ValueError):
        codec.encode_profile(
            profile, replace(codec.default_options(profile), **changes)
        )


def test_old_model_templates_are_not_replaced_or_silently_repaired():
    old = get_profiles_for_model(MODEL_NORMAL4)
    assert len(old) == 9
    for recipe in old:
        if recipe.key in {"refan", "sweet_rice"}:
            with pytest.raises(ValueError, match="checksum"):
                codec.default_options(recipe.profile)
    assert codec.duration_range(RECIPES["refan"]) == (30, 30)


def test_duration_grid_keeps_bounds_and_off_grid_default():
    assert duration_choices(25, 35, 30) == [25, 30, 35]
    assert duration_choices(28, 28, 28) == [28]
    assert duration_choices(40, 240, 90) == list(range(40, 241, 10))
    assert duration_choices(25, 35, 28) == [25, 28, 30, 35]
    assert duration_choices(1, 1440, 1440) == [1, *range(10, 1441, 10)]


@pytest.mark.parametrize("cmc", [False, True])
async def test_duration_selector_updates_atomically_with_default(
    hass, make_coordinator, cmc
):
    coordinator = make_coordinator(cmc)
    entities = await setup_platforms(hass, coordinator)
    duration = next(
        e for e in entities["select"] if getattr(e, "key", None) == "next_duration"
    )
    taste = next(
        e for e in entities["select"] if getattr(e, "key", None) == "next_taste"
    )
    warm = next(e for e in entities["switch"] if e.key == "next_auto_keep_warm")
    assert (
        not duration.available
        and duration.options == []
        and duration.current_option is None
    )
    snapshots = []

    def updated():
        snapshots.append(
            (duration.available, duration.current_option, duration.options)
        )

    remove_listener = coordinator.async_add_listener(updated)
    try:
        for recipe in coordinator.cooking_menu_options:
            await coordinator.async_select_cooking_menu(recipe)
            assert duration.available and duration.current_option in duration.options
            assert taste.available == (recipe == "jingzhu")
            assert warm.available == coordinator.recipe_codec.supports_option(
                coordinator.selected_recipe.profile, "auto_keep_warm"
            )
        await coordinator.async_select_cooking_menu("zhuzhou")
        assert duration.current_option == "90"
        await duration.async_select_option("120")
        with pytest.raises(HomeAssistantError):
            await duration.async_select_option("125")
        with pytest.raises(HomeAssistantError):
            await duration.async_select_option("9999")
        await coordinator.async_select_cooking_menu("refan")
        assert duration.options == (["25", "30", "35"] if cmc else ["30"])
        assert duration.current_option == "30"
        await coordinator.async_select_cooking_menu("zhuzhou")
        assert duration.current_option == "90"
        previous = coordinator.data
        coordinator.async_set_update_error(DeviceException("Offline"))
        assert not duration.available and not taste.available and not warm.available
        coordinator.async_set_updated_data(previous)
        assert duration.available and duration.current_option == "90"
        await coordinator.async_start_selected_profile()
        assert (
            not duration.available
            and duration.options == []
            and duration.current_option is None
        )
        assert not taste.available and not warm.available
        assert all(
            current in options for available, current, options in snapshots if available
        )
    finally:
        remove_listener()


async def test_normal3_controls_change_only_supported_header(hass, make_coordinator):
    coordinator = make_coordinator(False)
    entities = await setup_platforms(hass, coordinator)
    taste = next(
        e for e in entities["select"] if getattr(e, "key", None) == "next_taste"
    )
    warm = entities["switch"][0]
    await coordinator.async_select_cooking_menu("jingzhu")
    await taste.async_select_option("hard")
    await warm.async_turn_off()
    coordinator.api.start.assert_not_called()
    coordinator.api.set_setting.assert_not_called()
    await coordinator.async_start_selected_profile()
    raw = codec.decode_profile(coordinator.api.start.call_args.args[0])
    assert raw[:2] == b"\x00\x01" and raw[7] == 2 and raw[10] & 0x80 == 0
    assert raw[11:-2] == bytes.fromhex(RECIPES["jingzhu"])[11:-2]
    sent = coordinator.prepare_recipe(
        "zhuzhou", {"duration": 130, "auto_keep_warm": False}
    )
    assert codec.decode_profile(sent)[3:5] == bytes([2, 10])
    with pytest.raises(HomeAssistantError, match="schedule_unsupported"):
        coordinator.prepare_recipe("zhuzhou", {"finish_in": 180})


async def test_other_legacy_models_keep_existing_platforms(hass, make_coordinator):
    coordinator = make_coordinator(model=MODEL_NORMAL4)
    entities = await setup_platforms(hass, coordinator)
    assert len(entities["select"]) == 1
    assert entities["switch"] == entities["number"] == []
    profile = coordinator.cooking_menu_options[0]
    await coordinator.async_select_cooking_menu(profile)
    assert coordinator.recipe_options is None
    assert not coordinator.supports_option("duration")
    await coordinator.async_start_selected_profile()
    coordinator.api.start.assert_called_once_with(
        get_profiles_for_model(MODEL_NORMAL4)[0].profile
    )


async def test_normal3_additional_menu_feedback_keeps_old_enum_values(
    hass, make_coordinator
):
    coordinator = make_coordinator(False)
    entities = await setup_platforms(hass, coordinator)
    menu = next(e for e in entities["sensor"] if e.entity_description.key == "menu")
    for menu_id, expected in (
        (1, "jingzhu"),
        (2, "kuaizhu"),
        (260, "sweet_rice"),
        (493, "brown_rice"),
        (1615, "soup"),
    ):
        coordinator.async_set_updated_data(
            replace(
                coordinator.data, status=replace(coordinator.data.status, menu=menu_id)
            )
        )
        assert menu.native_value == expected
        assert expected in menu.options


@pytest.mark.parametrize("same_entry", [False, True])
async def test_duration_number_migration_is_scoped_to_entry(
    hass, monkeypatch, same_entry
):
    registry = Mock()
    registry.async_get_entity_id.return_value = "number.old_duration"
    registry.async_get.return_value = SimpleNamespace(
        config_entry_id="ours" if same_entry else "other"
    )
    monkeypatch.setattr(
        "custom_components.xiaomi_miio_cooker.er.async_get", lambda _: registry
    )
    _remove_replaced_duration_number(hass, SimpleNamespace(entry_id="ours"), "device")
    registry.async_get_entity_id.assert_called_once_with(
        "number", "xiaomi_miio_cooker", "device_next_duration"
    )
    assert registry.async_remove.call_count == int(same_entry)
