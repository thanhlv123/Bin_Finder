"""Voice-aligned, Windows-local video production."""


class ProductionError(RuntimeError):
    """An actionable production failure."""


class MissingSelectionError(ProductionError):
    """Cues need an eligible footage selection before production."""
