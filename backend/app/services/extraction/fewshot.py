"""Worked examples that can be shown to the model before the real document.

Off by default (``EXTRACTION_FEW_SHOT``). The two receipts here are INVENTED —
the shops, numbers and amounts exist nowhere — and were written by hand, not
taken from any dataset or any real document: an example drawn from the data a
model is later scored on would be a leak, not a demonstration.

They are text, not images. A page image costs about 1,300 tokens of the vision
model's 4,096-token context at ``VISION_RASTER_DPI``; two example images plus
the real one would not fit beside the field list. What an example teaches here
is the OUTPUT — values copied as printed, the shop's name from the header, and
null for what a receipt does not carry — and text shows that as well.

Answers are keyed by field, and the prompt shapes each one to the schema being
asked for (``prompts.build_user_prompt``), so the examples follow a tenant's
field list instead of fixing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FewShotExample:
    text: str
    """The receipt as its text would read."""
    answer: dict[str, str | None] = field(default_factory=dict)
    """Field key -> the value to extract. A key the schema asks for and this
    omits is shown as null."""


# An English till receipt that states its VAT: subtotal, VAT and total are three
# different printed amounts, and each goes to its own field.
_WITH_VAT = FewShotExample(
    text="""FRESH BASKET MARKET
Lakeside Mall Branch
VAT No: 300915527400003
Receipt No: 004518
Date: 17/03/2026   Time: 14:22
Cashier: 07
Basmati rice 5kg       1      46.00
Olive oil 1L           2      78.00
Subtotal                     124.00
VAT 15%                       18.60
TOTAL                 SAR    142.60
Cash                         150.00
Change                         7.40
Thank you for shopping with us""",
    answer={
        "invoice_number": "004518",
        "issue_date": "17/03/2026",
        "seller_name": "FRESH BASKET MARKET",
        "seller_trn": "300915527400003",
        "subtotal": "124.00",
        "vat_amount": "18.60",
        "total_amount": "142.60",
        "currency": "SAR",
    },
)

# An Arabic receipt with one amount and no VAT line: the total is the total, and
# the subtotal, VAT and VAT number are null because they are not printed.
_WITHOUT_VAT = FewShotExample(
    text="""صيدلية النور الجديدة
فرع شارع الجامعة
رقم الإيصال: 20931
التاريخ: 2026/08/05   الوقت: 09:41
باراسيتامول 500 ملغ    2     36.00
فيتامين سي             1     54.50
الإجمالي                     90.50
نقداً                       100.00
الباقي                        9.50
شكراً لزيارتكم""",
    answer={
        "invoice_number": "20931",
        "issue_date": "2026/08/05",
        "seller_name": "صيدلية النور الجديدة",
        "total_amount": "90.50",
    },
)

RECEIPT_EXAMPLES: tuple[FewShotExample, ...] = (_WITH_VAT, _WITHOUT_VAT)
