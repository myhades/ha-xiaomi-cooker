"""Data update coordinator for Xiaomi Cooker."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from miio import DeviceException

from . import cmc301_profile, normal3_profile
from .api import CookerData, UnsupportedModelError, XiaomiMiioCookerApi
from .const import (
    COMMAND_REFRESH_DELAY,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODEL_CMC301,
    MODEL_NORMAL3,
)
from .contracts import RecipeCodec
from .errors import command_error, recipe_error, validation_error
from .profiles import CookingProfile, get_cmc301_menu_key, get_menu_key
from .recipe_options import RecipeOptions, duration_choices

_LOGGER = logging.getLogger(__name__)

type XiaomiCookerConfigEntry = ConfigEntry[XiaomiMiioCookerCoordinator]


class XiaomiMiioCookerCoordinator(DataUpdateCoordinator[CookerData]):
    """Coordinate Xiaomi cooker updates and commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: XiaomiCookerConfigEntry,
        api: XiaomiMiioCookerApi,
        profiles: tuple[CookingProfile, ...],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=DEFAULT_UPDATE_INTERVAL,
            always_update=False,
            config_entry=entry,
        )
        self.api = api
        self.config_entry = entry
        self.device_unique_id = entry.unique_id or entry.entry_id
        self._command_lock = asyncio.Lock()
        self._profiles = profiles
        self._profiles_by_key = {profile.key: profile for profile in self._profiles}
        self._selected_profile: str | None = None
        self._selection_revision = 0
        self.recipe_options: RecipeOptions | None = None
        self._refresh_task: asyncio.Task | None = None
        entry.async_on_unload(self._cancel_delayed_refresh)

    @property
    def is_cmc301(self) -> bool:
        return self.config_entry.data.get("model") == MODEL_CMC301

    @property
    def recipe_codec(self) -> RecipeCodec | None:
        return {
            MODEL_CMC301: cmc301_profile,
            MODEL_NORMAL3: normal3_profile,
        }.get(self.config_entry.data.get("model"))

    @property
    def selected_recipe(self) -> CookingProfile | None:
        return self._profiles_by_key.get(self._selected_profile)

    @property
    def cooking_active(self) -> bool:
        return self.data is not None and self.data.status.status in {
            "running",
            "scheduled",
            "keep_warm",
            "busy",
        }

    @property
    def displayed_menu(self) -> str | None:
        if not self.cooking_active:
            return self._selected_profile
        menu = self.data.status.menu
        key = (
            get_cmc301_menu_key(menu)
            if self.is_cmc301
            else get_menu_key(menu, self.config_entry.data.get("model"))
        )
        if key in self._profiles_by_key:
            return key
        return "other" if menu is not None else None

    def displayed_parameter(self, key: str):
        if not self.cooking_active:
            return getattr(self.recipe_options, key, None)
        if key == "duration":
            return self.data.status.duration
        if key == "taste" and self.displayed_menu == "jingzhu":
            if self.is_cmc301:
                return self.data.properties.get("texture")
            stage = self.data.status.stage
            return stage.taste_phase if stage is not None else None
        return None

    def supports_option(self, key: str) -> bool:
        if self.recipe_options is None or self.selected_recipe is None:
            return False
        return self.recipe_codec.supports_option(self.selected_recipe.profile, key)

    @property
    def cooking_duration_options(self) -> list[str]:
        if not self.supports_option("duration"):
            return []
        profile = self.selected_recipe.profile
        return [
            str(value)
            for value in duration_choices(
                *self.recipe_codec.duration_range(profile),
                self.recipe_codec.default_options(profile).duration,
            )
        ]

    def set_recipe_option(self, key: str, value) -> None:
        if self.cooking_active:
            raise validation_error("cooker_busy")
        if not self.supports_option(key) or self.recipe_options is None:
            raise validation_error("unsupported_option")
        candidate = replace(self.recipe_options, **{key: value})
        try:
            self.recipe_codec.encode_profile(self.selected_recipe.profile, candidate)
        except ValueError as err:
            raise recipe_error(err) from err
        self.recipe_options = candidate
        self.async_update_listeners()

    @property
    def settings_writable(self) -> bool:
        return self.is_cmc301 or (
            self.data is not None and self.data.status.status == "idle"
        )

    async def async_set_setting(self, key: str, value) -> None:
        if not self.settings_writable:
            raise validation_error("cooker_busy")
        await self._async_execute_command(self.api.set_setting, key, value)

    async def async_select_panel_recipe(self, recipe: str) -> None:
        if recipe not in self.panel_recipe_options:
            raise validation_error("unsupported_recipe")
        if self.cooking_active:
            raise validation_error("cooker_busy")
        await self._async_execute_command(
            self.api.set_panel_recipe, self._profiles_by_key[recipe].profile
        )

    @property
    def panel_recipe_options(self) -> list[str]:
        if self.is_cmc301:
            return self.cooking_menu_options
        if self.config_entry.data.get("model") == MODEL_NORMAL3:
            return [p.key for p in self._profiles if int(p.profile[:4], 16) > 4]
        return []

    @property
    def device_name(self) -> str:
        """Return the device display name."""
        return DEFAULT_NAME

    @property
    def cooking_menu_options(self) -> list[str]:
        """Return selectable cooking menu options."""
        if not self._profiles:
            return []

        return [profile.key for profile in self._profiles]

    @property
    def selected_cooking_menu(self) -> str | None:
        """Return the currently selected cooking menu."""
        return self._selected_profile

    @property
    def panel_display_auto_off_enabled(self) -> bool | None:
        """Return whether idle panel display auto-off is enabled."""
        if self.data is None or self.data.settings is None:
            return None

        led_on = self.data.settings.led_on
        if led_on is None:
            return None

        return not led_on

    @property
    def lid_open_timeout_minutes(self) -> float | None:
        """Return the lid-open timeout in minutes."""
        if self.data is None or self.data.interaction_timeouts is None:
            return None

        lid_open = self.data.interaction_timeouts.lid_open
        if lid_open is None:
            return None

        return lid_open

    @property
    def lid_open_warning_enabled(self) -> bool | None:
        """Return whether delayed lid-open warning is enabled."""
        if self.data is None or self.data.settings is None:
            return None

        return self.data.settings.lid_open_warning_delayed

    async def _async_update_data(self) -> CookerData:
        """Fetch the latest cooker state."""
        try:
            return await self.hass.async_add_executor_job(self.api.fetch_data)
        except UnsupportedModelError as err:
            raise UpdateFailed(f"Unsupported Xiaomi cooker model: {err}") from err
        except DeviceException as err:
            raise UpdateFailed(f"Unable to update Xiaomi cooker state: {err}") from err

    async def async_start(self, profile: str) -> None:
        """Start a cooking profile."""
        await self._async_execute_command(self.api.start, profile)

    def prepare_recipe(self, recipe: str, options: dict) -> str:
        """Build an atomic automation request without changing the UI draft."""
        if self.recipe_codec is None or recipe not in self._profiles_by_key:
            raise validation_error("unsupported_recipe")
        profile = self._profiles_by_key[recipe].profile
        try:
            return self.recipe_codec.encode_profile(
                profile, replace(self.recipe_codec.default_options(profile), **options)
            )
        except (ValueError, TypeError) as err:
            raise recipe_error(err) from err

    async def async_stop(self) -> None:
        """Stop the cooking process."""
        await self._async_execute_command(self.api.stop)

    async def async_select_cooking_menu(self, option: str) -> None:
        """Select a cooking menu for the start button."""
        if self.cooking_active:
            raise validation_error("cooker_busy")
        if option not in self.cooking_menu_options:
            raise validation_error("unsupported_recipe")

        self._set_cooking_selection(option)

    def _set_cooking_selection(self, option: str | None) -> None:
        """Update the shared selector and its dependent draft together."""
        options = None
        if option is not None and self.recipe_codec is not None:
            options = self.recipe_codec.default_options(
                self._profiles_by_key[option].profile
            )
        self._selected_profile = option
        self.recipe_options = options
        self._selection_revision += 1
        self.async_update_listeners()

    def _clear_cooking_selection(self, revision: int) -> None:
        """Do not clear a new selection made while a command was in flight."""
        if self._selection_revision == revision:
            self._set_cooking_selection(None)

    async def async_start_selected_profile(self) -> None:
        """Resolve selection under the command lock to prevent duplicate starts."""
        async with self._command_lock:
            if self.cooking_active:
                raise validation_error("cooker_busy")
            if self.selected_recipe is None:
                raise validation_error("select_recipe")
            revision = self._selection_revision
            profile = self.selected_recipe.profile
            if self.recipe_options is not None:
                try:
                    profile = self.recipe_codec.encode_profile(
                        profile, self.recipe_options
                    )
                except ValueError as err:
                    raise recipe_error(err) from err
            if self.is_cmc301:
                # A lost response must not leave a one-click repeat armed.
                self._clear_cooking_selection(revision)
            await self._run_command(self.api.start, profile)
            self._clear_cooking_selection(revision)

    async def _async_execute_command(self, command, *args) -> None:
        async with self._command_lock:
            await self._run_command(command, *args)

    async def _run_command(self, command, *args) -> None:
        """Refresh even after an uncertain write; never repeat the write here."""
        try:
            await self.hass.async_add_executor_job(command, *args)
        except DeviceException as err:
            raise command_error(err) from err
        except ValueError as err:
            raise recipe_error(err) from err
        finally:
            await self.async_refresh()
            self._cancel_delayed_refresh()
            self._refresh_task = self.hass.async_create_task(
                self._async_delayed_refresh()
            )

    def _cancel_delayed_refresh(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    async def _async_delayed_refresh(self) -> None:
        await asyncio.sleep(COMMAND_REFRESH_DELAY)
        await self.async_refresh()
