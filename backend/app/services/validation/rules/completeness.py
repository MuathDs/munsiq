"""Completeness rules: what the schema requires must not quietly be empty.

A null is a legitimate answer for an OPTIONAL field — it is persisted as a
negative example, and marking it settled is correct. For a REQUIRED field it is
never settled: either the document lacks something the schema says it must
carry, or extraction missed it. Both need a person's eye.

The silent-miss check in extraction/labels.py already catches a null whose label
is printed on the page, but only when the page prints a label the schema knows.
A real invoice labelled its subtotal with a generic word ("المجموع", "sum") that
no subtotal synonym can safely include — it is also how totals are labelled —
so the null subtotal was written auto_validated. This rule does not depend on
the page at all: `required` in the schema is enough.

A warning, not an error: the reviewer can confirm a field that really is absent,
after looking. Blocking would make an honest null unconfirmable.
"""

from __future__ import annotations

from app.services.validation.engine import (
    RuleResult,
    Severity,
    ValidationContext,
    failure,
    rule,
)


@rule(
    "REQUIRED_FIELD_MISSING",
    Severity.WARNING,
    message_ar="حقل إلزامي فارغ.",
    message_en="A required field is empty.",
)
def required_fields_are_present(ctx: ValidationContext) -> list[RuleResult] | None:
    """Every field the schema marks required has a non-blank value.

    One finding per missing field, so each lands on its own field in the
    workspace. A required key with no row at all counts as missing too. Not
    applicable when the schema requires nothing.
    """
    if not ctx.required_keys:
        return None
    findings: list[RuleResult] = []
    for key in sorted(ctx.required_keys):
        value = ctx.value(key)
        if value is not None and value.strip():
            continue
        findings.append(
            failure(
                "REQUIRED_FIELD_MISSING",
                message_ar=(
                    f"الحقل الإلزامي «{key}» فارغ. تحقّق من المستند: إما أن القيمة "
                    "غير موجودة في الفاتورة، أو أنها لم تُقرأ."
                ),
                message_en=(
                    f"The required field '{key}' is empty. Check the document: either "
                    "the invoice does not carry it, or it was not read."
                ),
                field_key=key,
            )
        )
    return findings
