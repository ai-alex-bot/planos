"""planos: DXF floor plan -> space JSON -> GLB pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("planos")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"
