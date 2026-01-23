# re-export useful tools from this package due to,
# Re-export when any of these are true:
# - This package is meant to be imported by other repos
# - You want to control the “official” import path
# - You may move or rename internal modules later and want to avoid breaking imports
# - You want to document what is public vs internal

from .paths import get_file_paths

# for controlling import * behavior and,
# - __all__ documents public API
# - Pylance, mypy, IDEs understand this as intentional export
# - Your intent is now machine-readable
__all__ = ["get_file_paths"]
