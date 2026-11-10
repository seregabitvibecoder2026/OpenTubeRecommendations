"""Data providers. All unofficial parsing lives here so it can be fixed in one place.

Each provider function returns plain dicts or raises ProviderError / Unavailable.
"""


class ProviderError(RuntimeError):
    """Transient/unknown failure (network, parsing)."""


class Unavailable(ProviderError):
    """The source reliably does not have this data (e.g. age-restricted without login)."""
