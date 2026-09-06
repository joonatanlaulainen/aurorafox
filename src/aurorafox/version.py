"""Single source of truth for the package version.

Kept in its own module so low-level components (the HTTP User-Agent) can read it
without importing the package root, which imports them in turn.
"""

__version__ = "0.1.0"
