"""normal3 protocol, non-heating settings and model isolation."""

from binascii import crc_hqx
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from miio import DeviceException
from miio.cooker import TemperatureHistory

from custom_components.xiaomi_miio_cooker.api import (
    UnsupportedModelError,
    XiaomiMiioCookerApi,
    build_unique_id,
    normalize_token,
)
from custom_components.xiaomi_miio_cooker.const import MODEL_CMC301, MODEL_NORMAL3
from custom_components.xiaomi_miio_cooker.models import CookerDeviceMetadata
from custom_components.xiaomi_miio_cooker.normal3 import (
    Normal3Backend,
    _build_status_data,
    panel_profile,
)
from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model


def make_normal3():
    backend = Normal3Backend(
        "192.0.2.1",
        "0" * 32,
        CookerDeviceMetadata(MODEL_NORMAL3, "test", "test", "aa:bb:cc:dd:ee:ff"),
    )

    backend._cooker.send = Mock(return_value=["0100"])
    return backend


def test_normal3_wire_start_stop_unchanged():
    backend = make_normal3()
    backend._cooker._model = MODEL_NORMAL3
    backend._cooker.send = Mock(return_value=["ok"])
    profile = get_profiles_for_model(MODEL_NORMAL3)[0].profile
    backend.start(profile)
    backend._cooker.send.assert_called_with("set_start", [profile])
    backend.stop()
    backend._cooker.send.assert_called_with("set_func", ["end02"])


@pytest.mark.parametrize(
    "func,state",
    [
        ("waiting", "idle"),
        ("running", "running"),
        ("autokeepwarm", "keep_warm"),
        ("precook", "busy"),
        ("error", "unknown"),
    ],
)
def test_existing_state_contract(func, state):
    status = SimpleNamespace(
        data={"func": func, "menu": "0001"},
        remaining=10,
        duration=60,
        favorite=2,
        stage=None,
    )
    parsed = _build_status_data(status)
    assert parsed.status == state
    assert parsed.mode == "fine_cook"
    assert parsed.remaining == 10


def test_temperature_prefix_and_AA_marker_and_cache():
    backend = make_normal3()
    backend._cooker.get_temperature_history = Mock(
        return_value=TemperatureHistory("00021a1baa")
    )
    assert backend._get_temperature_from_history() == 27
    assert backend._get_temperature_from_history() == 27
    assert backend._cooker.get_temperature_history.call_count == 1


@pytest.mark.parametrize("raw", ["0", "", "0000aaaa", "0000"])
def test_empty_history_is_unknown_and_throttled(raw):
    backend = make_normal3()
    backend._cooker.get_temperature_history = Mock(return_value=TemperatureHistory(raw))
    assert [backend._get_temperature_from_history() for _ in range(3)] == [None] * 3
    assert backend._cooker.get_temperature_history.call_count == 1


def test_failed_history_does_not_retain_stale_sample():
    backend = make_normal3()
    backend._cached_temperature_from_history = 170
    backend._cooker.get_temperature_history = Mock(
        side_effect=DeviceException("timeout")
    )
    assert backend._get_temperature_from_history() is None
    assert backend._get_temperature_from_history() is None
    assert backend._cooker.get_temperature_history.call_count == 1


def test_token_and_identity():
    assert normalize_token("\ufeff \r\n" + "AB" * 16 + "\r\n") == "ab" * 16
    with pytest.raises(ValueError, match="32 hexadecimal"):
        normalize_token("secret")
    assert (
        build_unique_id("AA-BB-CC-DD-EE-FF", MODEL_NORMAL3)
        == "chunmi_cooker_normal3_aabbccddeeff"
    )


def test_model_mismatch_and_empty_info_fail_explicitly(metadata):
    api = XiaomiMiioCookerApi("192.0.2.1", "0" * 32, MODEL_NORMAL3)
    api._device_info = metadata
    with pytest.raises(UnsupportedModelError):
        api._get_backend()
    api._device_info = None
    api._device.info = Mock(return_value=None)
    with pytest.raises(DeviceException, match="No device information"):
        api.validate()


def test_raw_profiles_cannot_cross_models():
    normal = XiaomiMiioCookerApi("192.0.2.1", "0" * 32, MODEL_NORMAL3)
    cmc = XiaomiMiioCookerApi("192.0.2.2", "0" * 32, MODEL_CMC301)
    with pytest.raises(ValueError):
        normal.validate_profile(get_profiles_for_model(MODEL_CMC301)[0].profile)
    with pytest.raises(ValueError):
        cmc.validate_profile(get_profiles_for_model(MODEL_NORMAL3)[0].profile)


class Normal3Transport:
    def __init__(self):
        self.values = [
            "waiting",
            "0001",
            "null",
            "26",
            "60",
            "-1",
            "60",
            "1407",
            "050415",
            "0003000c",
            "0102",
            "0100140f0600011effff001e00001a1d",
        ]
        self.push = "0100"
        self.calls = []
        self.ignore_writes = False

    def send(self, method, params=None, **kwargs):
        self.calls.append((method, params, kwargs))
        if method == "get_prop":
            return self.values.copy()
        if method == "get_setting":
            return [self.push]
        if self.ignore_writes:
            return ["ok"]
        if method == "set_setting":
            self.push = params[0] + "01"  # Firmware marks the cloud sync flag dirty.
        elif method == "set_interaction":
            assert len(params) == 1
            flags, led, lid, alarm = (int(v, 16) for v in params[0].split(","))
            old = int(self.values[7][:2], 16)
            first = (
                (old & ~0x1A)
                | ((flags & 1) << 1)
                | ((flags & 2) << 2)
                | ((flags & 4) << 2)
            )
            self.values[7] = f"{first:02x}" + self.values[7][2:]
            self.values[8] = bytes((max(5, led), lid, alarm)).hex()
        elif method == "set_menu":
            data = bytes.fromhex(params[0])
            assert data[2] & 0x80 and crc_hqx(data[:-2], 0) == int.from_bytes(
                data[-2:], "big"
            )
            self.values[10] = data[:2].hex()
        else:
            raise AssertionError(f"Unapproved RPC {method}")
        return ["ok"]


@pytest.fixture
def device_backend():
    backend, transport = make_normal3(), Normal3Transport()
    backend._cooker._model = MODEL_NORMAL3
    backend._cooker.send = transport.send
    return backend, transport


def test_readbacks_and_optional_push_failure(device_backend):
    backend, transport = device_backend
    data = backend.fetch_data()
    assert data.properties["panel_recipe_id"] == 258
    assert data.properties["completion_notification"] is False
    assert data.properties["panel_auto_off"] is True
    assert data.properties["lid_open_timeout"] == 4
    transport.push = "invalid"
    data = backend.fetch_data()
    assert (
        data.status.status == "idle"
        and data.properties["completion_notification"] is None
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("panel_sleep", 7),
        ("panel_sleep", "off"),
        ("lid_open_warning", False),
        ("lid_open_timeout", 6),
        ("completion_notification", True),
    ],
)
def test_settings_round_trip_and_no_start(device_backend, key, value):
    backend, transport = device_backend
    backend.set_setting(key, value)
    state = backend.fetch_data()
    if key == "panel_sleep":
        assert state.properties["panel_auto_off"] == (value != "off")
        assert state.properties["display_timeout"] == (5 if value == "off" else value)
    else:
        assert state.properties[key] == value
    assert transport.values[7][2:] == "07"  # Preserve per-menu keep-warm flags.
    assert transport.values[8][4:] == "15"  # Preserve separate alarm delay.
    writes = [call for call in transport.calls if call[0].startswith("set_")]
    assert len(writes) == 1 and writes[0][2]["retry_count"] == 0


@pytest.mark.parametrize(
    "key,value", [("panel_sleep", 3), ("lid_open_timeout", 3), ("buzzer", True)]
)
def test_unsupported_settings_do_not_send(device_backend, key, value):
    backend, transport = device_backend
    with pytest.raises(ValueError):
        backend.set_setting(key, value)
    assert not transport.calls


def test_ignored_writes_and_busy_state_are_rejected(device_backend):
    backend, transport = device_backend
    transport.ignore_writes = True
    with pytest.raises(DeviceException):
        backend.set_setting("panel_sleep", 6)
    transport.calls.clear()
    transport.values[0] = "running"
    with pytest.raises(DeviceException):
        backend.set_setting("panel_sleep", "off")
    assert all(not call[0].startswith("set_") for call in transport.calls)


def test_custom_recipe_is_saved_and_read_independently(device_backend):
    backend, transport = device_backend
    recipe = next(r for r in get_profiles_for_model(MODEL_NORMAL3) if r.key == "soup")
    backend.set_panel_recipe(recipe.profile)
    assert backend.fetch_data().properties["panel_recipe_id"] == 1615
    assert transport.values[0] == "waiting"
    assert not any(call[0] == "set_start" for call in transport.calls)
    with pytest.raises(ValueError):
        panel_profile(get_profiles_for_model(MODEL_NORMAL3)[0].profile)


@pytest.mark.parametrize("setting,expected", [("1407", True), ("1007", False)])
def test_keep_warm_feedback_uses_current_flag_not_menu_flags(
    device_backend, setting, expected
):
    backend, transport = device_backend
    transport.values[7] = setting
    assert backend.fetch_data().properties["auto_keep_warm"] is expected
