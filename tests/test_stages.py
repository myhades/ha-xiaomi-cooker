"""Stage provenance and temperature-history lifecycle for supported cookers."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from miio import DeviceException
from miio.cooker import CookerStatus, TemperatureHistory
from test_entities import setup_platforms
from test_normal3 import make_normal3

from custom_components.xiaomi_miio_cooker.cmc301 import Cmc301Backend, parse_history
from custom_components.xiaomi_miio_cooker.stages import (
    RICE_PHASES,
    history_payload,
    rice_history_stage,
)


def raw_status(stage):
    return CookerStatus(
        {
            "func": "running",
            "menu": "0001",
            "stage": stage,
            "temp": "29",
            "t_func": "10",
            "t_precook": "-1",
            "t_cook": "60",
            "setting": "1407",
            "delay": "05040f",
            "version": "00030027",
            "favorite": "0100",
            "custom": "",
        }
    )


@pytest.mark.parametrize("index", range(5))
def test_five_history_phases_keep_markers_out_of_temperature(index):
    # Prefix bytes can contain AA and must not count as stage transitions.
    raw = "aaaa1a" + "aa30" * index
    stage = rice_history_stage(history_payload(raw))
    assert stage.state == index and stage.phase == RICE_PHASES[index]
    assert stage.rice_id is None and stage.taste is None
    assert 170 not in parse_history(raw)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "1a",
        "0000",
        "0000aa",
        "0000aaaa",
        "00001az",
        "0000zz",
        "00001a" + "aa" * 5,
    ],
)
def test_missing_invalid_and_unknown_history_has_no_fabricated_stage(raw):
    assert rice_history_stage(history_payload(raw)) is None


@pytest.mark.parametrize(
    "recipe,state,fault,expected",
    [
        (1, 2, 0, "water_absorption"),
        (2, 2, 0, "water_absorption"),
        (3, 2, 0, None),
        (1, 3, 0, None),
        (1, 5, 1, None),
        (1, 2, 1, None),
    ],
)
def test_cmc_phase_only_for_running_rice(
    device, metadata, recipe, state, fault, expected
):
    device.values.update(
        {(2, 19): recipe, (2, 1): state, (2, 2): fault, (2, 28): "00021aaa30"}
    )
    snapshot = Cmc301Backend(device, metadata).fetch_data()
    stage = snapshot.status.stage
    assert (stage.phase if stage else None) == expected
    assert snapshot.properties["recorded_temperature"] == 48
    assert snapshot.properties["stage_source"] == "temperature_history"


def test_stage_refresh_failure_and_state_transition_clear_cache(
    device, metadata, monkeypatch
):
    clock = [0.0]
    monkeypatch.setattr(
        "custom_components.xiaomi_miio_cooker.cmc301.monotonic", lambda: clock[0]
    )
    device.values.update({(2, 1): 2, (2, 28): "00021a"})
    backend = Cmc301Backend(device, metadata)
    assert backend.fetch_data().status.stage.phase == "quick_preheat"
    device.values[(2, 28)] = "00021aaa30aa40"
    clock[0] = 29
    assert backend.fetch_data().status.stage.phase == "quick_preheat"
    clock[0] = 30
    assert backend.fetch_data().status.stage.phase == "boiling"
    device.fail_properties.add((2, 28))
    clock[0] = 60
    assert backend.fetch_data().status.stage is None
    device.fail_properties.clear()
    clock[0] = 90
    assert backend.fetch_data().status.stage.phase == "boiling"
    # Fault and state changes invalidate the interpretation immediately.
    device.values[(2, 2)] = 1
    assert backend.fetch_data().status.stage is None
    device.values[(2, 2)] = 0
    device.values[(2, 1)] = 4
    assert backend.fetch_data().status.stage is None
    device.values[(2, 1)] = 1
    device.values[(2, 28)] = ""
    assert backend.fetch_data().status.stage is None
    device.values[(2, 1)] = 2
    assert backend.fetch_data().status.stage is None


@pytest.mark.parametrize(
    "raw", [None, "null", "", 7, "zz000000ff", "00000000", "0000000000ff"]
)
def test_malformed_legacy_stage_does_not_break_main_feedback(raw):
    backend = make_normal3()
    backend._cooker.status = Mock(return_value=raw_status(raw))
    backend._cooker.get_temperature_history = Mock(return_value=TemperatureHistory(""))
    snapshot = backend.fetch_data()
    assert snapshot.status.status == "running"
    assert snapshot.status.remaining == 10
    assert snapshot.status.stage is None
    assert snapshot.properties["stage_raw"] == raw


async def test_cmc_stage_entities_are_localized_and_cleared(
    hass, make_coordinator, device, metadata
):
    coordinator = make_coordinator()
    entities = await setup_platforms(hass, coordinator)
    sensors = {e.entity_description.key: e for e in entities["sensor"]}
    name = sensors["stage_name"]
    assert "stage_description" not in sensors
    assert name.unique_id.endswith("_stage_name")
    assert name.native_value is None
    backend = Cmc301Backend(device, metadata)
    device.values.update({(2, 1): 2, (2, 28): "00021aaa30"})
    coordinator.async_set_updated_data(backend.fetch_data())
    assert name.native_value == "water_absorption"
    assert name.options == list(RICE_PHASES)
    assert name.extra_state_attributes == {
        "description": "water_absorption",
        "source": "temperature_history",
        "stage_code": 1,
        "history_based": True,
    }
    root = Path(__file__).parents[1] / "custom_components/xiaomi_miio_cooker"
    for file in ("strings.json", "translations/en.json", "translations/zh-Hans.json"):
        strings = json.loads((root / file).read_text(encoding="utf-8"))["entity"][
            "sensor"
        ]
        for key in RICE_PHASES:
            assert strings["stage_name"]["state"][key]
            assert strings["stage_name"]["state_attributes"]["description"]["state"][
                key
            ]
            assert (
                len(
                    strings["stage_name"]["state_attributes"]["description"]["state"][
                        key
                    ]
                )
                < 255
            )
    device.values[(2, 1)] = 4
    coordinator.async_set_updated_data(backend.fetch_data())
    assert name.native_value is None
    assert name.extra_state_attributes["stage_code"] is None


async def test_normal3_stage_entities_use_official_history_with_raw_diagnostics(
    hass, make_coordinator
):
    coordinator = make_coordinator(False)
    entities = await setup_platforms(hass, coordinator)
    sensors = {e.entity_description.key: e for e in entities["sensor"]}
    backend = make_normal3()
    backend._cooker.status = Mock(return_value=raw_status("02000142ff"))
    backend._cooker.get_temperature_history = Mock(
        return_value=TemperatureHistory("00021aaa30")
    )
    coordinator.async_set_updated_data(backend.fetch_data())
    # Raw code 2 used to force "Boiling" even when the official curve says absorption.
    assert sensors["stage_name"].native_value == "water_absorption"
    assert "stage_description" not in sensors
    assert sensors["stage_name"].extra_state_attributes == {
        "description": "water_absorption",
        "source": "temperature_history",
        "stage_code": 2,
        "raw_stage": "02000142ff",
        "history_based": True,
        "phase_index": 1,
    }
    assert sensors["stage_name"].options == list(RICE_PHASES)
    assert (
        sensors["stage_name"].unique_id == coordinator.device_unique_id + "_stage_name"
    )


@pytest.mark.parametrize(
    "func,menu",
    [
        ("precook", "0001"),
        ("autokeepwarm", "0001"),
        ("running", "0003"),
        ("running", "0102"),
    ],
)
def test_normal3_does_not_apply_rice_phases_to_other_modes(func, menu):
    backend = make_normal3()
    status = raw_status("02000142ff")
    status.data.update(func=func, menu=menu)
    backend._cooker.status = Mock(return_value=status)
    backend._cooker.get_temperature_history = Mock(
        return_value=TemperatureHistory("00021aaa30")
    )
    stage = backend.fetch_data().status.stage
    assert stage.phase is None
    assert stage.state == 2 and stage.name is None and stage.description is None


def test_normal3_history_lifecycle_and_no_generic_fallback(monkeypatch):
    clock = [0]
    monkeypatch.setattr(
        "custom_components.xiaomi_miio_cooker.normal3.monotonic", lambda: clock[0]
    )
    backend = make_normal3()
    status = raw_status("fe000142ff")
    backend._cooker.status = Mock(return_value=status)
    history = backend._cooker.get_temperature_history = Mock(
        return_value=TemperatureHistory("00021a")
    )
    assert backend.fetch_data().status.stage.phase == "quick_preheat"
    history.return_value = TemperatureHistory("00021aaa30aa40")
    clock[0] = 29
    assert backend.fetch_data().status.stage.phase == "quick_preheat"
    assert history.call_count == 1
    clock[0] = 30
    assert backend.fetch_data().status.stage.phase == "boiling"
    history.side_effect = DeviceException("History unavailable")
    clock[0] = 60
    snapshot = backend.fetch_data()
    assert snapshot.status.stage.phase is None
    assert snapshot.status.stage.state == 254
    assert snapshot.status.status == "running" and snapshot.temperature == 29
    assert snapshot.properties["history_phase_index"] is None
    history.side_effect = None
    status.data["func"] = "autokeepwarm"
    assert backend.fetch_data().status.stage.phase is None
    status.data["func"] = "running"
    history.return_value = TemperatureHistory("00021aaa30")
    assert backend.fetch_data().status.stage.phase == "water_absorption"
    status.data["menu"] = "0002"
    history.return_value = TemperatureHistory("")
    assert backend.fetch_data().status.stage.phase is None


def test_normal3_raw_stage_parsing_does_not_require_dependency_text():
    class RawStage:
        state, rice_id, taste, taste_phase = 3, 1, 66, 2

        @property
        def name(self):
            raise AssertionError("normal3 must not read the generic stage table")

        @property
        def description(self):
            raise AssertionError("normal3 must not read the generic stage table")

    from custom_components.xiaomi_miio_cooker.normal3 import _build_stage_data

    stage = _build_stage_data(RawStage(), legacy_text=False)
    assert stage.state == 3 and stage.name is None and stage.description is None


def test_normal3_warm_type_and_completion_preserve_device_minutes():
    backend = make_normal3()
    for func, menu, stage, kind, finished in [
        ("running", "0001", "03000042ff", "none", False),
        ("running", "0001", "10000042ff", "none", True),
        ("autokeepwarm", "0001", "10000042ff", "automatic", True),
        ("running", "0004", "03000042ff", "manual", False),
        ("autokeepwarm", "0004", "10000042ff", "manual", False),
        ("error", "0001", "10000042ff", "none", False),
        ("precook", "0001", "10000042ff", "none", False),
    ]:
        raw = raw_status(stage)
        raw.data.update(func=func, menu=menu)
        backend._cooker.status = Mock(return_value=raw)
        backend._cooker.get_temperature_history = Mock(
            return_value=TemperatureHistory("0")
        )
        data = backend.fetch_data()
        assert data.status.remaining == (None if func == "precook" else 10)
        assert data.properties["keep_warm_type"] == kind
        assert data.properties["cooking_finished"] is finished
        assert data.properties["time_direction"] == (
            "elapsed" if kind != "none" else "remaining"
        )


@pytest.mark.parametrize("cmc", [False, True])
async def test_warm_phase_entities_preserve_recipe_and_control_guards(
    hass, make_coordinator, device, metadata, cmc
):
    coordinator = make_coordinator(cmc)
    entities = await setup_platforms(hass, coordinator)
    sensors = {entity.entity_description.key: entity for entity in entities["sensor"]}
    backend = Cmc301Backend(device, metadata) if cmc else make_normal3()
    raw = raw_status("03000042ff")
    if not cmc:
        backend._cooker.status = Mock(return_value=raw)
        backend._cooker.get_temperature_history = Mock(
            return_value=TemperatureHistory("0")
        )
    for phase, menu, expected_status, expected_duration in [
        ("cooking", 2 if cmc else 1, "running", 60),
        ("automatic", 2 if cmc else 1, "automatic_keep_warm", 1440),
        ("manual", 4, "keep_warm", 60),
        ("unknown", 0, None, None),
        ("idle", 4, "idle", None),
    ]:
        if cmc:
            device.values.update(
                {
                    (2, 1): 2 if phase == "cooking" else 1 if phase == "idle" else 4,
                    (2, 19): menu,
                    (2, 20): 60,
                    (2, 21): 85800 if phase == "automatic" else 3000,
                }
            )
        else:
            raw.data.update(
                func="running"
                if phase in ("cooking", "manual")
                else "waiting"
                if phase == "idle"
                else "keepwarm"
                if phase == "unknown"
                else "autokeepwarm",
                menu=f"{menu:04x}",
            )
        coordinator.async_set_updated_data(backend.fetch_data())
        assert sensors["status"].native_value == expected_status
        assert sensors["current_duration"].native_value == expected_duration
        assert "automatic_keep_warm" in sensors["status"].options
        assert sensors["status"].extra_state_attributes is None
        assert not entities["button"][0].available  # No prepared recipe.
        assert entities["button"][1].available == (phase != "idle")
        assert entities["select"][0].available == (phase == "idle")
        if phase in ("manual", "automatic"):
            assert sensors["remaining"].native_value == 10
            assert sensors["current_menu"].native_value == (
                "baowen" if phase == "manual" else "jingzhu"
            )
            assert sensors["current_taste"].native_value is None
