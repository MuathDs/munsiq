"""Deterministic validation: rule registry, context, and runner.

This module is what makes extraction trustworthy. A language model produces a
plausible answer; these rules decide whether it is an arithmetically and legally
coherent one. Nothing here calls a model, touches the network, or reads the
database — every rule is a pure function over a ``ValidationContext`` and is
unit-testable on its own.

Contract for a rule:

* decorated with ``@rule(code, severity, message_ar, message_en)``
* takes exactly one argument, the context
* returns a list of ``RuleResult`` (empty list means "checked, and it passed")
* returns ``None`` when the rule does not apply to this document — a credit
  note has no sequence fields to check, a scan has no QR to compare against.
  "Not applicable" is deliberately distinct from "passed".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

# Money comparisons are exact to the halala, with a one-halala tolerance for
# rounding differences between a supplier's system and ours. Decimal only:
# a float comparison here would produce findings that come and go.
TOLERANCE: Final[Decimal] = Decimal("0.01")
CENTS: Final[Decimal] = Decimal("0.01")

STANDARD_VAT_RATE: Final[Decimal] = Decimal("15")
ZERO_VAT_RATE: Final[Decimal] = Decimal("0")

VAT_CATEGORIES: Final[frozenset[str]] = frozenset({"S", "Z", "E", "O"})
"""ZATCA VAT category codes: Standard, Zero-rated, Exempt, Out-of-scope."""

CREDIT_NOTE_TYPE_CODE: Final[str] = "381"
DEBIT_NOTE_TYPE_CODE: Final[str] = "383"
SIMPLIFIED_THRESHOLD_SAR: Final[Decimal] = Decimal("1000")


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class RuleResult:
    code: str
    severity: Severity
    passed: bool
    message_ar: str
    message_en: str
    field_key: str | None = None

    @property
    def is_blocking(self) -> bool:
        """An unresolved error prevents confirmation."""
        return self.severity is Severity.ERROR and not self.passed


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FieldView:
    """One extracted field, as the rules see it."""

    key: str
    value: str | None
    source: str | None = None
    shadow_value: str | None = None
    """The model's answer for a field that UBL owns. Drives XML_PDF_MISMATCH."""

    @property
    def from_ubl(self) -> bool:
        return self.source == "ubl_xml"

    @property
    def from_human(self) -> bool:
        """A reviewer chose this value.

        Matters for the anti-hallucination guard: that rule exists because
        *models* fabricate. A reviewer is looking at the rendered page and has
        authority the model does not — including the authority to correct a
        value that OCR misread, which by definition will not match the OCR text.
        """
        return self.source == "human"


@dataclass(frozen=True)
class LineItem:
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_amount: Decimal | None = None
    name: str | None = None


@dataclass
class ValidationContext:
    """Everything the rules are allowed to see. No DB handle, no model client."""

    fields: dict[str, FieldView] = field(default_factory=dict)
    numeric_keys: frozenset[str] = frozenset()
    lines: list[LineItem] = field(default_factory=list)

    page_text: str = ""
    """Concatenated, normalized text of every page. Backs OCR_SUBSTRING_MISSING."""

    invoice_type_code: str | None = None
    invoice_type_name: str | None = None
    vat_category: str | None = None
    vat_percent: Decimal | None = None

    qr_decoded: dict[int, str] | None = None
    has_icv: bool = False
    has_pih: bool = False
    has_embedded_ubl: bool = False

    pdf_has_arabic: bool = False
    """True when the rendered document contains Arabic text."""

    def value(self, key: str) -> str | None:
        entry = self.fields.get(key)
        return entry.value if entry else None

    def amount(self, key: str) -> Decimal | None:
        """Parse a field as Decimal. Never float."""
        return to_decimal(self.value(key))

    @property
    def is_credit_note(self) -> bool:
        return self.invoice_type_code == CREDIT_NOTE_TYPE_CODE

    # ZATCA encodes the transaction type in InvoiceTypeCode/@name, a seven
    # character string. The first TWO characters carry the subtype:
    #     "01" -> standard tax invoice
    #     "02" -> simplified tax invoice
    # and the remaining five are binary flags (third party, nominal, exports,
    # summary, self-billed).
    #
    # CAVEAT, deliberately visible: a second reading of the same field is in
    # circulation, treating all seven characters as independent binary flags, so
    # that "1000000" is standard and "0100000" is simplified. Under that reading
    # every value below means the opposite. We follow the 01/02 subtype
    # convention because it is what ZATCA's own sample invoices carry. This is
    # one of the things a real certified sample would settle — see the
    # outstanding xfail in tests/test_ubl.py.
    STANDARD_PREFIX: Final[str] = "01"
    SIMPLIFIED_PREFIX: Final[str] = "02"

    @property
    def _type_name(self) -> str:
        return (self.invoice_type_name or "").strip()

    @property
    def is_simplified(self) -> bool:
        return self._type_name.startswith(self.SIMPLIFIED_PREFIX)

    @property
    def is_standard(self) -> bool:
        return self._type_name.startswith(self.STANDARD_PREFIX)


def to_decimal(raw: str | Decimal | None) -> Decimal | None:
    """Parse money without ever going through float."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    text = raw.strip().replace(",", "").replace("٫", ".").replace("٬", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def money(value: Decimal) -> Decimal:
    return value.quantize(CENTS)


def close_enough(left: Decimal, right: Decimal, tolerance: Decimal = TOLERANCE) -> bool:
    return abs(money(left) - money(right)) <= tolerance


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
RuleFn = Callable[[ValidationContext], list[RuleResult] | None]


@dataclass(frozen=True)
class RuleSpec:
    code: str
    severity: Severity
    message_ar: str
    message_en: str
    fn: RuleFn


_REGISTRY: dict[str, RuleSpec] = {}


def rule(
    code: str, severity: Severity, message_ar: str, message_en: str
) -> Callable[[RuleFn], RuleFn]:
    """Register a rule.

    The messages here are the rule's summary. Individual findings usually build
    a more specific message with the actual values, because "the totals do not
    add up" is far less useful to a reviewer than "45,320.00 + 6,798.00 =
    52,118.00, but the invoice says 52,000.00".
    """

    def decorate(fn: RuleFn) -> RuleFn:
        if code in _REGISTRY:
            raise ValueError(f"duplicate rule code: {code}")
        _REGISTRY[code] = RuleSpec(
            code=code, severity=severity, message_ar=message_ar, message_en=message_en, fn=fn
        )
        fn.__rule_code__ = code  # type: ignore[attr-defined]
        return fn

    return decorate


def registry() -> dict[str, RuleSpec]:
    return dict(_REGISTRY)


def passed(spec: RuleSpec, field_key: str | None = None) -> RuleResult:
    return RuleResult(
        code=spec.code,
        severity=spec.severity,
        passed=True,
        message_ar=spec.message_ar,
        message_en=spec.message_en,
        field_key=field_key,
    )


def failure(
    code: str, message_ar: str, message_en: str, field_key: str | None = None
) -> RuleResult:
    spec = _REGISTRY[code]
    return RuleResult(
        code=code,
        severity=spec.severity,
        passed=False,
        message_ar=message_ar,
        message_en=message_en,
        field_key=field_key,
    )


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
@dataclass
class ValidationReport:
    results: list[RuleResult] = field(default_factory=list)

    @property
    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed]

    @property
    def blockers(self) -> list[str]:
        """Distinct rule codes that must be resolved before confirmation."""
        seen: list[str] = []
        for result in self.results:
            if result.is_blocking and result.code not in seen:
                seen.append(result.code)
        return seen

    @property
    def blocking_field_keys(self) -> set[str]:
        """Fields to mark validation_state='blocking'."""
        return {r.field_key for r in self.results if r.is_blocking and r.field_key}

    @property
    def warned_field_keys(self) -> set[str]:
        """Fields a non-blocking warning is about: worth a second look, not a stop."""
        return {
            r.field_key
            for r in self.results
            if r.severity is Severity.WARNING and not r.passed and r.field_key
        }

    @property
    def is_confirmable(self) -> bool:
        return not self.blockers


def run_rules(context: ValidationContext) -> ValidationReport:
    """Run every registered rule. Order is irrelevant — rules are independent."""
    report = ValidationReport()
    for spec in _REGISTRY.values():
        outcome = spec.fn(context)
        if outcome is None:
            # Not applicable to this document. Records nothing, so a scan is not
            # penalised for lacking a QR code it was never required to have.
            continue
        if not outcome:
            report.results.append(passed(spec))
            continue
        report.results.extend(outcome)
    return report
