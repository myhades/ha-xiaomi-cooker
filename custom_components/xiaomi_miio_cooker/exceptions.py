"""Protocol error codes independent of Home Assistant."""

from miio import DeviceException


class RecipeValidationError(ValueError):
    """A recipe validation failure with a translatable reason."""

    def __init__(self, key: str, message: str, **placeholders: object) -> None:
        super().__init__(message)
        self.key = key
        self.placeholders = {key: str(value) for key, value in placeholders.items()}


class CookerCommandError(DeviceException):
    """A known device-side rejection or uncertain result."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key
