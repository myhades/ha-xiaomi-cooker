"""Constants for the Xiaomi Cooker integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "xiaomi_miio_cooker"

CONF_MODEL = "model"

ATTR_PROFILE = "profile"

SERVICE_START = "start"
SERVICE_START_RECIPE = "start_recipe"


DEFAULT_NAME = "Xiaomi Cooker"
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)
# Both official plugins specify a 24-hour automatic keep-warm limit.
AUTO_KEEP_WARM_MINUTES = 1440
COMMAND_REFRESH_DELAY = 2
TEMPERATURE_HISTORY_MIN_INTERVAL_SECONDS = 120
MANUFACTURER = "Xiaomi"

RAW_DIAGNOSTIC_PROPERTIES = (
    "recipe_id",
    "recipe_type",
    "status_code",
    "mode_code",
    "reset_flag",
    "history_samples",
)

MODEL_PRESSURE1 = "chunmi.cooker.press1"
MODEL_PRESSURE2 = "chunmi.cooker.press2"
MODEL_NORMAL1 = "chunmi.cooker.normal1"
MODEL_NORMAL2 = "chunmi.cooker.normal2"
MODEL_NORMAL3 = "chunmi.cooker.normal3"
MODEL_NORMAL4 = "chunmi.cooker.normal4"
MODEL_NORMAL5 = "chunmi.cooker.normal5"

MODEL_CMC301 = "xiaomi.cooker.cmc301"

SUPPORTED_MODELS = (MODEL_CMC301, MODEL_NORMAL3)

PLATFORMS = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
]
