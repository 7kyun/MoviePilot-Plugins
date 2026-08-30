class MetatubeError(Exception):
    """Base error for the Metatube integration."""


class MetatubeTransportError(MetatubeError):
    pass


class MetatubeProtocolError(MetatubeError):
    pass


class MetatubeNotFoundError(MetatubeError):
    pass


class MetatubeValidationError(MetatubeError):
    """Metatube rejected request parameters (HTTP 422)."""
    pass
