"""ZATCA compliance rules.

These encode Saudi e-invoicing requirements rather than general accounting
sense. They are what let the product say something a generic OCR tool cannot:
not just "we read this number" but "this invoice is or is not compliant, and
here is which clause it fails".
"""

from __future__ import annotations

from decimal import Decimal

from app.services.ubl import (
    QR_TAG_TOTAL_WITH_VAT,
    QR_TAG_VAT_TOTAL,
    validate_trn,
)
from app.services.validation.engine import (
    SIMPLIFIED_THRESHOLD_SAR,
    STANDARD_VAT_RATE,
    VAT_CATEGORIES,
    ZERO_VAT_RATE,
    RuleResult,
    Severity,
    ValidationContext,
    close_enough,
    failure,
    money,
    rule,
    to_decimal,
)

SELLER_TRN = "seller_trn"
BUYER_TRN = "buyer_trn"
TOTAL_AMOUNT = "total_amount"
VAT_AMOUNT = "vat_amount"


@rule(
    "TRN_CHECKSUM",
    Severity.ERROR,
    message_ar="الرقم الضريبي لا يطابق الصيغة المعتمدة من هيئة الزكاة والضريبة والجمارك.",
    message_en="A VAT registration number fails the ZATCA structural check.",
)
def trns_are_structurally_valid(ctx: ValidationContext) -> list[RuleResult] | None:
    """Seller and buyer TRNs must pass validate_trn.

    Structural only — it proves the number is well formed, not that it is
    registered to anybody. A buyer TRN is legitimately absent on simplified
    invoices, so absence is not a failure here.
    """
    findings: list[RuleResult] = []
    checked = 0
    for key in (SELLER_TRN, BUYER_TRN):
        value = ctx.value(key)
        if not value:
            continue
        checked += 1
        if validate_trn(value):
            continue
        findings.append(
            failure(
                "TRN_CHECKSUM",
                message_ar=(
                    f"الرقم الضريبي «{value}» غير صالح. يجب أن يتكون من 15 رقماً، "
                    f"وأن يبدأ بالرقم 3 وينتهي بالرقم 3، وأن يكون الرقم الحادي عشر 1."
                ),
                message_en=(
                    f"VAT number '{value}' is not valid: it must be 15 digits, start "
                    f"with 3, end with 3, and carry '1' in the 11th position."
                ),
                field_key=key,
            )
        )
    if checked == 0:
        return None
    return findings


@rule(
    "VAT_CATEGORY_VALID",
    Severity.ERROR,
    message_ar="رمز فئة الضريبة غير معروف.",
    message_en="The VAT category code is not one ZATCA recognises.",
)
def vat_category_is_known(ctx: ValidationContext) -> list[RuleResult] | None:
    """The category must be S, Z, E or O."""
    if ctx.vat_category is None:
        return None
    category = ctx.vat_category.strip().upper()
    if category in VAT_CATEGORIES:
        return []
    return [
        failure(
            "VAT_CATEGORY_VALID",
            message_ar=(
                f"رمز فئة الضريبة «{ctx.vat_category}» غير معروف. "
                f"القيم المسموح بها هي: S (أساسية) أو Z (صفرية) أو E (معفاة) "
                f"أو O (خارج نطاق الضريبة)."
            ),
            message_en=(
                f"VAT category '{ctx.vat_category}' is not recognised. Allowed "
                f"values are S (standard), Z (zero-rated), E (exempt) and "
                f"O (out of scope)."
            ),
        )
    ]


@rule(
    "VAT_RATE_CONSISTENT",
    Severity.ERROR,
    message_ar="نسبة الضريبة لا تتوافق مع فئة الضريبة المذكورة.",
    message_en="The VAT rate is inconsistent with the declared VAT category.",
)
def vat_rate_matches_category(ctx: ValidationContext) -> list[RuleResult] | None:
    """Category S implies 15%. Z and E imply 0%."""
    if ctx.vat_category is None or ctx.vat_percent is None:
        return None
    category = ctx.vat_category.strip().upper()

    expected: Decimal | None
    if category == "S":
        expected = STANDARD_VAT_RATE
    elif category in {"Z", "E"}:
        expected = ZERO_VAT_RATE
    else:
        # 'O' is out of scope; no rate is implied.
        return None

    if ctx.vat_percent == expected:
        return []
    return [
        failure(
            "VAT_RATE_CONSISTENT",
            message_ar=(
                f"فئة الضريبة «{category}» تستلزم نسبة {expected}%، "
                f"بينما الفاتورة تذكر نسبة {ctx.vat_percent}%."
            ),
            message_en=(
                f"VAT category '{category}' implies a rate of {expected}%, but the "
                f"invoice states {ctx.vat_percent}%."
            ),
        )
    ]


@rule(
    "INVOICE_TYPE_THRESHOLD",
    Severity.WARNING,
    message_ar="فاتورة مبسّطة بمبلغ يبلغ أو يتجاوز 1000 ريال.",
    message_en="A simplified invoice at or above SAR 1,000.",
)
def simplified_invoice_below_threshold(ctx: ValidationContext) -> list[RuleResult] | None:
    """Warn when a simplified invoice carries a large total.

    A warning, not an error: the threshold governs which document type the
    supplier should have issued, and that is the supplier's compliance problem,
    not a reason to block the buyer from booking the invoice.
    """
    if not ctx.is_simplified:
        return None
    total = ctx.amount(TOTAL_AMOUNT)
    if total is None:
        return None
    if total < SIMPLIFIED_THRESHOLD_SAR:
        return []
    return [
        failure(
            "INVOICE_TYPE_THRESHOLD",
            message_ar=(
                f"الفاتورة مبسّطة بينما إجماليها ({money(total)} ريال) يبلغ أو "
                f"يتجاوز 1000 ريال؛ يُتوقع في هذه الحالة إصدار فاتورة ضريبية."
            ),
            message_en=(
                f"This is a simplified invoice, but its total ({money(total)} SAR) is "
                f"at or above SAR 1,000, where a standard tax invoice is expected."
            ),
            field_key=TOTAL_AMOUNT,
        )
    ]


@rule(
    "QR_TOTAL_MATCH",
    Severity.ERROR,
    message_ar="القيم المشفّرة في رمز الاستجابة السريعة لا تطابق القيم المستخرجة.",
    message_en="The values encoded in the ZATCA QR code do not match the extracted totals.",
)
def qr_totals_match_extracted(ctx: ValidationContext) -> list[RuleResult] | None:
    """TLV tag 4 (total with VAT) and tag 5 (VAT total) must agree with the fields.

    The QR is generated by the supplier's own system from the same data it
    reported to ZATCA. A disagreement means we read the document wrong, or the
    document disagrees with itself.
    """
    if not ctx.qr_decoded:
        return None

    findings: list[RuleResult] = []
    checked = 0
    for tag, key, label_ar, label_en in (
        (QR_TAG_TOTAL_WITH_VAT, TOTAL_AMOUNT, "الإجمالي شامل الضريبة", "total with VAT"),
        (QR_TAG_VAT_TOTAL, VAT_AMOUNT, "مبلغ الضريبة", "VAT amount"),
    ):
        encoded = to_decimal(ctx.qr_decoded.get(tag))
        extracted = ctx.amount(key)
        if encoded is None or extracted is None:
            continue
        checked += 1
        if close_enough(encoded, extracted):
            continue
        findings.append(
            failure(
                "QR_TOTAL_MATCH",
                message_ar=(
                    f"{label_ar} في رمز الاستجابة السريعة ({money(encoded)}) "
                    f"لا يطابق القيمة المستخرجة ({money(extracted)})."
                ),
                message_en=(
                    f"The {label_en} encoded in the QR code ({money(encoded)}) does "
                    f"not match the extracted value ({money(extracted)})."
                ),
                field_key=key,
            )
        )
    if checked == 0:
        return None
    return findings


@rule(
    "SEQUENCE_FIELDS_PRESENT",
    Severity.WARNING,
    message_ar="الفاتورة الضريبية تفتقر إلى مرجع العداد التسلسلي أو تجزئة الفاتورة السابقة.",
    message_en="A standard tax invoice is missing its ICV or PIH reference.",
)
def standard_invoice_has_sequence_fields(ctx: ValidationContext) -> list[RuleResult] | None:
    """Standard invoices must carry ICV (invoice counter) and PIH (previous hash).

    Only meaningful when we have the UBL to look in — their absence from a
    plain scan says nothing about the supplier's compliance.
    """
    if not ctx.has_embedded_ubl or not ctx.is_standard:
        return None
    if ctx.has_icv and ctx.has_pih:
        return []

    missing_ar = []
    missing_en = []
    if not ctx.has_icv:
        missing_ar.append("مرجع العداد التسلسلي (ICV)")
        missing_en.append("ICV (invoice counter value)")
    if not ctx.has_pih:
        missing_ar.append("تجزئة الفاتورة السابقة (PIH)")
        missing_en.append("PIH (previous invoice hash)")

    return [
        failure(
            "SEQUENCE_FIELDS_PRESENT",
            message_ar=(
                "الفاتورة ضريبية (وليست مبسّطة) ولكنها لا تتضمن: " + "، ".join(missing_ar) + "."
            ),
            message_en=(
                "This is a standard tax invoice but it is missing: " + ", ".join(missing_en) + "."
            ),
        )
    ]
