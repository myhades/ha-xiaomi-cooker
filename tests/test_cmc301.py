from binascii import crc_hqx
from dataclasses import replace

import pytest
from miio import DeviceException

from custom_components.xiaomi_miio_cooker.cmc301 import Cmc301Backend, parse_history
from custom_components.xiaomi_miio_cooker.cmc301_profile import (
    decode_profile,
    default_options,
    encode_profile,
    validate_bundled_profile,
)
from custom_components.xiaomi_miio_cooker.const import MODEL_CMC301
from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model

RECIPES = get_profiles_for_model(MODEL_CMC301)


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r.key)
def test_all_official_templates_and_default_roundtrip(recipe):
    data = decode_profile(recipe.profile)
    assert len(data) == 176
    assert (
        encode_profile(recipe.profile, default_options(recipe.profile))
        == recipe.profile
    )
    validate_bundled_profile(recipe.profile)


def test_recipe_ids_and_parameter_byte_layout():
    quick, fine, congee = RECIPES[:3]
    assert int(quick.profile[6:14], 16) == 1
    assert int(fine.profile[6:14], 16) == 2
    modified = encode_profile(
        congee.profile,
        replace(
            default_options(congee.profile),
            duration=120,
            finish_in=500,
            auto_keep_warm=False,
        ),
    )
    data = decode_profile(modified)
    assert data[8:10] == bytes([2, 0])
    assert data[14:16] == bytes([0x88, 20])
    assert data[20:-2] == decode_profile(congee.profile)[20:-2]
    validate_bundled_profile(modified)
    tasted = encode_profile(
        fine.profile, replace(default_options(fine.profile), taste=2)
    )
    assert decode_profile(tasted)[19] == 2
    validate_bundled_profile(tasted)


@pytest.mark.parametrize(
    "key,value",
    [
        ("duration", 29),
        ("taste", 1),
        ("finish_in", 40),
        ("finish_in", 1440),
        ("duration", True),
        ("auto_keep_warm", 1),
    ],
)
def test_quick_rice_rejects_unsupported_options(key, value):
    profile = RECIPES[0].profile
    with pytest.raises(ValueError):
        encode_profile(profile, replace(default_options(profile), **{key: value}))


def test_corrupt_and_unknown_heating_program_rejected():
    profile = RECIPES[0].profile
    with pytest.raises(ValueError):
        decode_profile(profile[:-4] + "0000")
    data = bytearray.fromhex(profile)
    data[80] ^= 1
    data[-2:] = crc_hqx(data[:-2], 0).to_bytes(2, "big")
    with pytest.raises(ValueError):
        validate_bundled_profile(data.hex())


def test_feedback_units_partial_errors_and_history(device, metadata):
    backend = Cmc301Backend(device, metadata)
    snapshot = backend.fetch_data()
    assert snapshot.status.mode == "quick_cook"
    assert snapshot.status.remaining == 61 / 60
    assert snapshot.properties["recorded_temperature"] == 27
    assert snapshot.temperature is None
    device.fail_properties.add((2, 26))
    device.fail_actions.add((6, 2))
    snapshot = backend.fetch_data()
    assert snapshot.properties["texture"] is None
    assert snapshot.properties["panel_auto_off"] is None
    assert snapshot.status.status == "idle"
    device.fail_properties.add((2, 1))
    with pytest.raises(DeviceException):
        backend.fetch_data()


@pytest.mark.parametrize(
    "raw,expected",
    [("1a", ()), ("", ()), ("zzzzzz", ()), ("0000aaaa", ()), ("0002001baa", (0, 27))],
)
def test_history(raw, expected):
    assert parse_history(raw) == expected


def test_start_stop_and_save_use_correct_actions(device, metadata):
    backend = Cmc301Backend(device, metadata)
    backend.start(RECIPES[0].profile)
    assert device.calls[-1] == (
        "action",
        {
            "did": "miot",
            "siid": 2,
            "aiid": 6,
            "in": [{"piid": 27, "value": RECIPES[0].profile}],
        },
        0,
    )
    backend.set_panel_recipe(RECIPES[2].profile)
    panel = device.calls[-1][1]
    assert panel["aiid"] == 5
    assert panel["in"][0]["value"].startswith("info_")
    assert decode_profile(panel["in"][0]["value"][5:])[2] == 4
    device.values[(7, 1)] = False
    backend.stop()
    assert device.calls[-1][1] == {"did": "miot", "siid": 2, "aiid": 2, "in": []}


@pytest.mark.parametrize(
    "property,value", [((2, 1), 2), ((2, 2), 5), ((7, 1), False), ((7, 1), None)]
)
def test_start_requires_fresh_idle_fault_and_permission(
    device, metadata, property, value
):
    device.values[property] = value
    with pytest.raises(DeviceException):
        Cmc301Backend(device, metadata).start(RECIPES[0].profile)
    assert all(call[0] != "action" for call in device.calls)


def test_start_timeout_never_retries(device, metadata):
    device.timeout_start = True
    with pytest.raises(DeviceException, match="not confirmed"):
        Cmc301Backend(device, metadata).start(RECIPES[0].profile)
    actions = [call for call in device.calls if call[0] == "action"]
    assert len(actions) == 1 and actions[0][2] == 0


def test_setting_preserves_other_bytes_and_checks_readback(device, metadata):
    backend = Cmc301Backend(device, metadata)
    device.settings = "0005017f"
    backend.set_setting("display_timeout", 6)
    assert device.settings == "0006017f"
    backend.set_setting("completion_notification", True)
    assert device.settings == "0006007f"
    device.ignore_writes = True
    with pytest.raises(DeviceException, match="not confirmed"):
        backend.set_setting("panel_auto_off", False)


def test_invalid_profile_sends_nothing(device, metadata):
    with pytest.raises(ValueError):
        Cmc301Backend(device, metadata).start("00" * 121)
    assert device.calls == []


def test_recorded_hardware_session_and_history_lifecycle(device, metadata, monkeypatch):
    """Replay real scheduled/instant responses, including late-arriving history."""
    import json
    from pathlib import Path

    from custom_components.xiaomi_miio_cooker.cmc301 import PROPERTIES

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/cmc301_hardware_session.json").read_text()
    )
    backend = Cmc301Backend(device, metadata)
    clock = [0.0]
    monkeypatch.setattr(
        "custom_components.xiaomi_miio_cooker.cmc301.monotonic", lambda: clock[0]
    )
    scheduled_temperature_seen = False
    for row in fixture["observations"]:
        clock[0] = row["elapsed_s"]
        for key, address in PROPERTIES.items():
            device.values[address] = row["properties"][key]
        device.values[(2, 28)] = row["history"][0]["value"]
        snapshot = backend.fetch_data()
        assert snapshot.status.duration == 60
        if row["run"] == "fine_immediate":
            assert snapshot.status.status == "running"
            assert snapshot.properties["texture"] == 2
            assert snapshot.status.menu == 2
        else:
            # Even below the cooking duration, raw code 3 must not be relabeled
            # as running: the device does not expose a separate heater state.
            assert snapshot.status.status == "scheduled"
            assert snapshot.status.menu == 3
            assert (
                snapshot.status.remaining == row["properties"]["remaining_seconds"] / 60
            )
            if row["elapsed_s"] >= 68:
                assert snapshot.properties["recorded_temperature"] == 26
                scheduled_temperature_seen = True
    assert scheduled_temperature_seen
    clock[0] += 2
    device.values[(2, 1)] = 1
    device.values[(2, 28)] = ""
    snapshot = backend.fetch_data()
    assert snapshot.status.status == "idle"
    assert snapshot.properties["recorded_temperature"] is None
