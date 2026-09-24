"""Regression contracts for the existing normal3 release."""

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
from custom_components.xiaomi_miio_cooker.legacy import (
    LegacyCookerBackend,
    _build_status_data,
)
from custom_components.xiaomi_miio_cooker.models import CookerDeviceMetadata
from custom_components.xiaomi_miio_cooker.profiles import get_profiles_for_model


def make_legacy():
    backend = LegacyCookerBackend(
        "192.0.2.1",
        "0" * 32,
        CookerDeviceMetadata(MODEL_NORMAL3, "test", "test", "aa:bb:cc:dd:ee:ff"),
    )

    backend._cooker.send = Mock(return_value=["0100"])
    return backend


def test_normal3_wire_start_stop_unchanged():
    backend = make_legacy()
    backend._cooker._model = MODEL_NORMAL3
    backend._cooker.send = Mock(return_value=["ok"])
    profile = get_profiles_for_model(MODEL_NORMAL3)[0].profile
    backend.start(profile)
    backend._cooker.send.assert_called_with("set_start", [profile])
    backend.stop()
    backend._cooker.send.assert_called_with("set_func", ["end02"])


def test_normal3_menu_and_template_compatibility():
    recipes = get_profiles_for_model(MODEL_NORMAL3)
    assert [r.key for r in recipes][:9] == [
        "jingzhu",
        "kuaizhu",
        "zhuzhou",
        "baowen",
        "cake",
        "yoghurt",
        "refan",
        "cooking",
        "sweet_rice",
    ]
    assert all(len(r.profile) == 242 for r in recipes)
    assert [r.key for r in recipes][9:] == ["brown_rice", "soup"]
    from custom_components.xiaomi_miio_cooker.normal3_profile import decode_profile

    assert all(decode_profile(r.profile) for r in recipes)


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
    backend = make_legacy()
    backend._cooker.get_temperature_history = Mock(
        return_value=TemperatureHistory("00021a1baa")
    )
    assert backend._get_temperature_from_history() == 27
    assert backend._get_temperature_from_history() == 27
    assert backend._cooker.get_temperature_history.call_count == 1


@pytest.mark.parametrize("raw", ["0", "", "0000aaaa", "0000"])
def test_empty_history_is_unknown_and_throttled(raw):
    backend = make_legacy()
    backend._cooker.get_temperature_history = Mock(return_value=TemperatureHistory(raw))
    assert [backend._get_temperature_from_history() for _ in range(3)] == [None] * 3
    assert backend._cooker.get_temperature_history.call_count == 1


def test_failed_history_does_not_retain_stale_sample():
    backend = make_legacy()
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
