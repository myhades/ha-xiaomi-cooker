"""Stable protocol errors and translated HA errors without raw device messages."""

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from miio import DeviceException

from .const import DOMAIN
from .exceptions import CookerCommandError, RecipeValidationError


def validation_error(key: str, **placeholders: object) -> ServiceValidationError:
    """Local validation failures never include credentials or raw payloads."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={
            key: str(value) for key, value in placeholders.items()
        },
    )


def recipe_error(error: ValueError | TypeError) -> ServiceValidationError:
    if isinstance(error, RecipeValidationError):
        return validation_error(error.key, **error.placeholders)
    return validation_error("invalid_parameters")


def command_error(error: DeviceException) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=error.key
        if isinstance(error, CookerCommandError)
        else "command_failed",
    )
