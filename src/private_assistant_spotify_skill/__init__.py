"""This package allows to use spotify within the private assistant ecosystem."""

try:
    from ._version import __version__
except ImportError:
    # Fallback for development installs
    __version__ = "dev"

__all__ = ["__version__"]
