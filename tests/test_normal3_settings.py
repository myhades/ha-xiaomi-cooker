"""Non-heating RPCs matched against normal3 firmware 0003000c captures."""

from binascii import crc_hqx

import pytest
from miio import DeviceException
from test_legacy import make_legacy

from custom_components.xiaomi_miio_cooker.const import MODEL_NORMAL3
from custom_components.xiaomi_miio_cooker.normal3_profile import panel_profile
from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model


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
    backend, transport = make_legacy(), Normal3Transport()
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
