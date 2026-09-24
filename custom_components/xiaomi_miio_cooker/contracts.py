"""Structural contracts shared by the model-specific implementations."""

from typing import Any, Protocol, runtime_checkable

from .models import CookerData, CookerDeviceMetadata
from .recipe_options import RecipeOptions


class CookerBackend(Protocol):
    """Every backend provides snapshots and independent start/stop commands."""

    metadata: CookerDeviceMetadata

    def fetch_data(self) -> CookerData: ...
    def start(self, profile: str) -> Any: ...
    def stop(self) -> Any: ...


@runtime_checkable
class SettingsBackend(Protocol):
    """Optional settings capability, distinct from cooking support."""

    def set_setting(self, key: str, value: Any) -> None: ...


@runtime_checkable
class PanelRecipeBackend(Protocol):
    """Optional panel recipe storage capability."""

    def set_panel_recipe(self, profile: str) -> None: ...


class RecipeCodec(Protocol):
    """Common recipe interface; wire layouts remain model-specific."""

    def default_options(self, profile: str) -> RecipeOptions: ...
    def duration_range(self, profile: str) -> tuple[int, int]: ...
    def supports_option(self, profile: str, key: str) -> bool: ...
    def encode_profile(self, profile: str, options: RecipeOptions) -> str: ...
