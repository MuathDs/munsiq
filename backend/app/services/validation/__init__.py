"""Deterministic validation.

Importing this package pulls in the rule modules, which register themselves
with the engine as a side effect of import.
"""

from __future__ import annotations

from app.services.validation import rules as _rules  # noqa: F401 - registers rules
from app.services.validation.engine import (
    FieldView,
    LineItem,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationReport,
    registry,
    run_rules,
)

__all__ = [
    "FieldView",
    "LineItem",
    "RuleResult",
    "Severity",
    "ValidationContext",
    "ValidationReport",
    "registry",
    "run_rules",
]
