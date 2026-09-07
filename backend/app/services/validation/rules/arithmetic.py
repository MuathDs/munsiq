"""Arithmetic rules.

An invoice that does not add up is wrong regardless of how confident any model
was about it. These are the cheapest and most reliable checks in the system.

Every comparison uses Decimal with explicit quantize and a one-halala tolerance.
Never float: 0.1 + 0.2 != 0.3 in binary floating point, and a validation engine
that flickers between pass and fail on rounding is worse than no engine.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.validation.engine import (
    STANDARD_VAT_RATE,
    RuleResult,
    Severity,
    ValidationContext,
    close_enough,
    failure,
    money,
    rule,
)

SUBTOTAL = "subtotal"
VAT_AMOUNT = "vat_amount"
TOTAL_AMOUNT = "total_amount"

_AMOUNT_KEYS = (SUBTOTAL, VAT_AMOUNT, TOTAL_AMOUNT)


@rule(
    "LINE_TOTAL_MISMATCH",
    Severity.ERROR,
    message_ar="مجموع بنود الفاتورة لا يطابق المجموع قبل الضريبة.",
    message_en="The sum of the line items does not match the subtotal.",
)
def line_total_matches_subtotal(ctx: ValidationContext) -> list[RuleResult] | None:
    """sum(quantity x unit price) == subtotal.

    Not applicable when no line items were extracted — the Phase 3+4 schema does
    not request them, so this fires only for documents parsed from UBL.
    """
    if not ctx.lines:
        return None
    subtotal = ctx.amount(SUBTOTAL)
    if subtotal is None:
        return None

    computed = Decimal("0")
    usable = 0
    for line in ctx.lines:
        if line.quantity is not None and line.unit_price is not None:
            computed += line.quantity * line.unit_price
            usable += 1
        elif line.line_amount is not None:
            computed += line.line_amount
            usable += 1
    if usable == 0:
        return None

    if close_enough(computed, subtotal):
        return []
    return [
        failure(
            "LINE_TOTAL_MISMATCH",
            message_ar=(
                f"مجموع البنود المحتسب ({money(computed)}) لا يطابق "
                f"المجموع قبل الضريبة المذكور في الفاتورة ({money(subtotal)})."
            ),
            message_en=(
                f"Line items add up to {money(computed)}, but the invoice states a "
                f"subtotal of {money(subtotal)}."
            ),
            field_key=SUBTOTAL,
        )
    ]


@rule(
    "LINE_ITEM_PRICE_MISMATCH",
    Severity.WARNING,
    message_ar="قيمة أحد البنود لا تطابق حاصل ضرب الكمية في سعر الوحدة.",
    message_en="A line item's amount does not match quantity x unit price.",
)
def line_item_amounts_are_consistent(ctx: ValidationContext) -> list[RuleResult] | None:
    """Each line's own amount must equal its quantity times its unit price."""
    if not ctx.lines:
        return None

    findings: list[RuleResult] = []
    checked = 0
    for index, line in enumerate(ctx.lines, start=1):
        if line.quantity is None or line.unit_price is None or line.line_amount is None:
            continue
        checked += 1
        expected = line.quantity * line.unit_price
        if close_enough(expected, line.line_amount):
            continue
        findings.append(
            failure(
                "LINE_ITEM_PRICE_MISMATCH",
                message_ar=(
                    f"البند رقم {index}: الكمية ({line.quantity}) × سعر الوحدة "
                    f"({money(line.unit_price)}) = {money(expected)}، "
                    f"بينما قيمة البند المذكورة هي {money(line.line_amount)}."
                ),
                message_en=(
                    f"Line {index}: quantity ({line.quantity}) x unit price "
                    f"({money(line.unit_price)}) = {money(expected)}, but the line "
                    f"amount is {money(line.line_amount)}."
                ),
            )
        )
    if checked == 0:
        return None
    return findings


@rule(
    "VAT_CALC_MISMATCH",
    Severity.ERROR,
    message_ar="مبلغ ضريبة القيمة المضافة لا يطابق النسبة المطبقة على المجموع.",
    message_en="The VAT amount does not match the rate applied to the subtotal.",
)
def vat_amount_matches_rate(ctx: ValidationContext) -> list[RuleResult] | None:
    """subtotal x rate == vat_amount.

    Falls back to the standard 15% when the document does not state a rate,
    because that is what a Saudi tax invoice charges by default.
    """
    subtotal = ctx.amount(SUBTOTAL)
    vat_amount = ctx.amount(VAT_AMOUNT)
    if subtotal is None or vat_amount is None:
        return None

    rate = ctx.vat_percent if ctx.vat_percent is not None else STANDARD_VAT_RATE
    expected = subtotal * rate / Decimal("100")

    if close_enough(expected, vat_amount):
        return []
    return [
        failure(
            "VAT_CALC_MISMATCH",
            message_ar=(
                f"ضريبة القيمة المضافة بنسبة {rate}% على مبلغ {money(subtotal)} "
                f"تساوي {money(expected)}، بينما المبلغ المذكور في الفاتورة هو "
                f"{money(vat_amount)}."
            ),
            message_en=(
                f"VAT at {rate}% on {money(subtotal)} is {money(expected)}, but the "
                f"invoice states {money(vat_amount)}."
            ),
            field_key=VAT_AMOUNT,
        )
    ]


@rule(
    "GRAND_TOTAL_MISMATCH",
    Severity.ERROR,
    message_ar="الإجمالي لا يساوي المجموع قبل الضريبة مضافاً إليه الضريبة.",
    message_en="The total does not equal subtotal plus VAT.",
)
def grand_total_adds_up(ctx: ValidationContext) -> list[RuleResult] | None:
    """subtotal + vat_amount == total_amount."""
    subtotal = ctx.amount(SUBTOTAL)
    vat_amount = ctx.amount(VAT_AMOUNT)
    total = ctx.amount(TOTAL_AMOUNT)
    if subtotal is None or vat_amount is None or total is None:
        return None

    expected = subtotal + vat_amount
    if close_enough(expected, total):
        return []
    return [
        failure(
            "GRAND_TOTAL_MISMATCH",
            message_ar=(
                f"المجموع قبل الضريبة ({money(subtotal)}) مضافاً إليه الضريبة "
                f"({money(vat_amount)}) يساوي {money(expected)}، بينما الإجمالي "
                f"المذكور هو {money(total)}."
            ),
            message_en=(
                f"Subtotal ({money(subtotal)}) plus VAT ({money(vat_amount)}) is "
                f"{money(expected)}, but the stated total is {money(total)}."
            ),
            field_key=TOTAL_AMOUNT,
        )
    ]


@rule(
    "NEGATIVE_AMOUNT",
    Severity.ERROR,
    message_ar="الفاتورة تحتوي على مبلغ سالب.",
    message_en="The invoice contains a negative amount.",
)
def amounts_are_not_negative(ctx: ValidationContext) -> list[RuleResult] | None:
    """No negative amounts — unless the document is a credit note, where they
    are the entire point."""
    if ctx.is_credit_note:
        return None

    findings: list[RuleResult] = []
    checked = 0
    for key in _AMOUNT_KEYS:
        amount = ctx.amount(key)
        if amount is None:
            continue
        checked += 1
        if amount >= 0:
            continue
        findings.append(
            failure(
                "NEGATIVE_AMOUNT",
                message_ar=(
                    f"الحقل «{key}» يحتوي على قيمة سالبة ({money(amount)})، "
                    f"وهذا غير مقبول إلا في إشعار دائن."
                ),
                message_en=(
                    f"Field '{key}' is negative ({money(amount)}). That is only "
                    f"valid on a credit note."
                ),
                field_key=key,
            )
        )
    if checked == 0:
        return None
    return findings
