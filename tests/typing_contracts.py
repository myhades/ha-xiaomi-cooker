"""Static compatibility checks; no device objects are instantiated."""

from custom_components.xiaomi_miio_cooker import cmc301, normal3
from custom_components.xiaomi_miio_cooker.cmc301 import Cmc301Backend
from custom_components.xiaomi_miio_cooker.contracts import (
    CookerBackend,
    PanelRecipeBackend,
    RecipeCodec,
    SettingsBackend,
)
from custom_components.xiaomi_miio_cooker.normal3 import Normal3Backend


def backends(
    cmc301: Cmc301Backend, legacy: Normal3Backend
) -> tuple[CookerBackend, CookerBackend, SettingsBackend, PanelRecipeBackend]:
    return cmc301, legacy, cmc301, cmc301


def codecs() -> tuple[RecipeCodec, RecipeCodec]:
    return cmc301, normal3
