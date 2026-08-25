"""Errors that can be reported to launcher users without a traceback."""


class LauncherError(Exception):
    """Base class for a user-correctable launcher failure."""


class ConfigError(LauncherError):
    """Raised when launcher configuration is invalid."""
