"""Rule modules.

Importing this package registers every rule with the engine. Adding a module
here is all that is needed for its rules to run.
"""

from __future__ import annotations

from app.services.validation.rules import arithmetic, provenance, zatca

__all__ = ["arithmetic", "provenance", "zatca"]
