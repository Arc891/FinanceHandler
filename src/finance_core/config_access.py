"""
Late, defaulted access to config.config_settings.

The Google layer reads its settings when it is used rather than when it is
imported, so the modules can be imported (and tested) without a local config,
and a key that only exists during the Phase 1-3 transition can have a default.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setting(name, default=None):
    """config_settings.<name>, or ``default`` when the key or the module is absent."""
    try:
        import config.config_settings as cs
    except ImportError:
        return default
    return getattr(cs, name, default)


def project_path(path) -> str:
    """Resolve a path relative to the project root; absolute paths pass through."""
    path = os.fspath(path)
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
