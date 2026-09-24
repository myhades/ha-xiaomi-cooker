"""Config flow for Xiaomi Cooker."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from miio import DeviceException

from .api import (
    UnsupportedModelError,
    XiaomiMiioCookerApi,
    build_entry_title,
    build_unique_id,
    normalize_token,
)
from .const import CONF_MODEL, DOMAIN, MODEL_AUTO, SUPPORTED_MODELS

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class CannotDetectModel(Exception):
    """Error to indicate automatic model detection failed."""


def _log_connection_failure(stage: str, err: Exception, token: str) -> None:
    """Expose connection errors without logging credentials or traceback locals."""
    detail = str(err)
    normalized = "".join(token.replace("\ufeff", "").split())
    for secret in (token, normalized):
        if secret:
            detail = re.sub(re.escape(secret), "[redacted]", detail, flags=re.I)
    detail = re.sub(r"[0-9a-fA-F]{32}", "[redacted]", detail)
    _LOGGER.warning(
        "Cooker connection validation failed during %s: %s: %s",
        stage,
        type(err).__name__,
        detail,
    )


async def _async_validate_input(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> dict[str, str | None]:
    """Validate the user input allows us to connect."""
    selected_model = data.get(CONF_MODEL) or MODEL_AUTO
    configured_model = None if selected_model == MODEL_AUTO else selected_model
    api = XiaomiMiioCookerApi(
        host=data[CONF_HOST],
        token=data[CONF_TOKEN],
        model=configured_model,
    )

    metadata = None
    if configured_model is None:
        try:
            metadata = await hass.async_add_executor_job(api.fetch_device_info)
        except DeviceException as err:
            _log_connection_failure("miIO.info", err, data[CONF_TOKEN])
            raise CannotConnect from err

        if not metadata.model:
            raise CannotDetectModel

        if metadata.model not in SUPPORTED_MODELS:
            raise UnsupportedModelError(f"Unsupported device found: {metadata.model}")

    try:
        if configured_model is None:
            initial_data = await hass.async_add_executor_job(api.fetch_data)
        else:
            initial_data = await hass.async_add_executor_job(api.validate)
    except UnsupportedModelError as err:
        raise UnsupportedModelError from err
    except DeviceException as err:
        _log_connection_failure(
            "initial status read" if configured_model is None else "device validation",
            err,
            data[CONF_TOKEN],
        )
        raise CannotConnect from err

    metadata = metadata or initial_data.device_info
    resolved_model = configured_model or metadata.model
    if not resolved_model:
        raise CannotDetectModel

    return {
        "title": build_entry_title(),
        "unique_id": build_unique_id(
            metadata.mac_address,
            metadata.model or resolved_model,
            data[CONF_HOST],
        ),
        "model": resolved_model,
        "mac_address": metadata.mac_address,
    }


class XiaomiMiioCookerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xiaomi cooker."""

    VERSION = 1

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify identity before changing connection data, preserving entities."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(entry.data)
            data[CONF_HOST] = user_input[CONF_HOST].strip()
            try:
                # A blank password field keeps the stored token without displaying it.
                submitted_token = user_input.get(CONF_TOKEN, "")
                if submitted_token.replace("\ufeff", "").strip():
                    data[CONF_TOKEN] = normalize_token(submitted_token)
                info = await _async_validate_input(self.hass, data)
            except ValueError:
                errors["base"] = "invalid_token"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except CannotDetectModel:
                errors["base"] = "cannot_detect_model"
            except UnsupportedModelError:
                errors["base"] = "unsupported_model"
            except Exception:
                _LOGGER.exception("Unexpected exception during cooker reconfiguration")
                errors["base"] = "unknown"
            else:
                if not info["mac_address"]:
                    errors["base"] = "cannot_verify_identity"
                else:
                    await self.async_set_unique_id(info["unique_id"])
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(entry, data_updates=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=(user_input or entry.data)[CONF_HOST]
                    ): str,
                    vol.Optional(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                user_input[CONF_TOKEN] = normalize_token(user_input[CONF_TOKEN])
                user_input[CONF_HOST] = user_input[CONF_HOST].strip()
                info = await _async_validate_input(self.hass, user_input)
            except ValueError:
                errors["base"] = "invalid_token"
            except CannotDetectModel:
                errors["base"] = "cannot_detect_model"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except UnsupportedModelError:
                errors["base"] = "unsupported_model"
            except Exception:  # pragma: no cover - defensive HA flow guard
                _LOGGER.exception("Unexpected exception during Xiaomi cooker setup")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured(
                    updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_TOKEN: user_input[CONF_TOKEN],
                        CONF_MODEL: info["model"],
                    }
                )
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_TOKEN: user_input[CONF_TOKEN],
                        CONF_MODEL: info["model"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def _build_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Build the config flow schema."""
        user_input = user_input or {}
        model_options = {
            MODEL_AUTO: "Auto",
            **{model: model for model in SUPPORTED_MODELS},
        }
        schema: dict = {
            vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
            vol.Required(CONF_TOKEN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_MODEL,
                default=user_input.get(CONF_MODEL) or MODEL_AUTO,
            ): vol.In(model_options),
        }

        return vol.Schema(schema)
