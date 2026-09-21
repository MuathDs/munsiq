"""Provenance rules — where a value came from, and whether the document agrees.

``OCR_SUBSTRING_MISSING`` is the primary anti-hallucination guard in the whole
system. A language model will happily produce a well-formed, plausible, wholly
invented number. The one thing it cannot do is make that number appear on the
page. So every numeric value is checked against the document's own text.
"""

from __future__ import annotations

from app.services.normalize import has_arabic, normalize_for_match, normalize_text
from app.services.validation.engine import (
    RuleResult,
    Severity,
    ValidationContext,
    failure,
    rule,
)

SELLER_NAME = "seller_name"
BUYER_NAME = "buyer_name"


@rule(
    "XML_PDF_MISMATCH",
    Severity.ERROR,
    message_ar="تعارض بين قيمة ملف XML الموقّع وقيمة استخرجها النموذج.",
    message_en="A field's signed XML value disagrees with the model's reading.",
)
def xml_and_model_agree(ctx: ValidationContext) -> list[RuleResult] | None:
    """Flag any field where UBL and the model disagree.

    The XML value is authoritative — it is what the supplier cryptographically
    signed and reported. The disagreement still matters: it means either our
    reading of the rendered page is wrong, or the PDF a human looks at does not
    say the same thing as the XML a machine files. Both are worth a reviewer's
    attention, so this is an error rather than a warning.
    """
    findings: list[RuleResult] = []
    compared = 0
    for key, entry in ctx.fields.items():
        if not entry.from_ubl or entry.value is None or entry.shadow_value is None:
            continue
        compared += 1
        if normalize_for_match(entry.value) == normalize_for_match(entry.shadow_value):
            continue
        findings.append(
            failure(
                "XML_PDF_MISMATCH",
                message_ar=(
                    f"تعارض في الحقل «{key}»: ملف XML الموقّع يذكر "
                    f"«{entry.value}» بينما استخرج النموذج «{entry.shadow_value}» "
                    f"من صورة المستند. القيمة المعتمدة هي قيمة XML."
                ),
                message_en=(
                    f"Field '{key}' disagrees: the signed XML says '{entry.value}' "
                    f"while the model read '{entry.shadow_value}' from the rendered "
                    f"page. The XML value is authoritative."
                ),
                field_key=key,
            )
        )
    if compared == 0:
        return None
    return findings


@rule(
    "OCR_SUBSTRING_MISSING",
    Severity.ERROR,
    message_ar="قيمة رقمية مستخرجة لا تظهر في نص المستند.",
    message_en="An extracted numeric value does not appear in the document text.",
)
def numeric_values_appear_on_the_page(ctx: ValidationContext) -> list[RuleResult] | None:
    """Every numeric field's value must occur in the page text.

    THE ANTI-HALLUCINATION GUARD. Comparison happens after normalization on both
    sides, so Arabic-Indic digits, thousands separators and invisible format
    characters do not cause false alarms.

    TWO EXEMPTIONS, both load-bearing:

    * **UBL values.** They were read from a signed attachment, not the rendered
      page, and a compliant invoice can carry a value in its XML that is not
      printed on its face.
    * **Human corrections.** This rule exists because *models* fabricate. A
      reviewer is looking at the document and has authority the model does not —
      including the authority to fix a value that OCR misread, which by
      definition will not appear in the OCR text. Applying the guard to human
      input would make a bad OCR read permanently unfixable: every correction
      would re-trigger the blocker it was meant to clear.
    """
    if not ctx.page_text.strip():
        # No text was extracted at all — the page-level failure is already
        # reported by the pipeline. Repeating it per field would be noise.
        return None

    haystack = normalize_for_match(ctx.page_text)
    haystack_digits = _digits_only(haystack)

    findings: list[RuleResult] = []
    checked = 0
    for key in sorted(ctx.numeric_keys):
        entry = ctx.fields.get(key)
        if entry is None or entry.value is None or entry.from_ubl or entry.from_human:
            continue
        needle = normalize_for_match(entry.value)
        if not needle:
            continue
        checked += 1

        if needle in haystack:
            continue
        # Second chance on digits alone: the page may print "52,118.00" where
        # the model returned "52118.00". That is a formatting difference, not a
        # fabrication.
        needle_digits = _digits_only(needle)
        if needle_digits and needle_digits in haystack_digits:
            continue

        findings.append(
            failure(
                "OCR_SUBSTRING_MISSING",
                message_ar=(
                    f"القيمة «{entry.value}» للحقل «{key}» لا تظهر في نص المستند. "
                    f"قد تكون القيمة مُختلقة، ويجب التحقق منها يدوياً."
                ),
                message_en=(
                    f"The value '{entry.value}' for field '{key}' does not appear "
                    f"anywhere in the document text. It may be fabricated and must "
                    f"be checked by a human."
                ),
                field_key=key,
            )
        )
    if checked == 0:
        return None
    return findings


def _digits_only(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


@rule(
    "ARABIC_ENCODING_SUSPECT",
    Severity.WARNING,
    message_ar="المستند يعرض نصاً عربياً بينما أسماء الأطراف في ملف XML فارغة أو تالفة.",
    message_en=(
        "The document renders Arabic but the embedded XML party names are empty or mis-encoded."
    ),
)
def arabic_survived_the_xml(ctx: ValidationContext) -> list[RuleResult] | None:
    """A real, documented ZATCA Phase 2 integration failure.

    Some e-invoicing integrations write party names into the UBL with a broken
    encoding, so the PDF a human reads shows proper Arabic while the XML a
    machine files contains empty strings or mojibake. Catching it protects the
    buyer from filing a supplier's encoding bug as their own data.
    """
    if not ctx.has_embedded_ubl or not ctx.pdf_has_arabic:
        return None

    findings: list[RuleResult] = []
    checked = 0
    for key in (SELLER_NAME, BUYER_NAME):
        entry = ctx.fields.get(key)
        if entry is None or not entry.from_ubl:
            continue
        checked += 1
        value = entry.value or ""
        if not value.strip():
            findings.append(_encoding_finding(key, "empty"))
            continue
        if _looks_like_mojibake(value):
            findings.append(_encoding_finding(key, "mojibake", value))
    if checked == 0:
        return None
    return findings


_REPLACEMENT = "�"


def _looks_like_mojibake(value: str) -> bool:
    """Heuristic: replacement characters, or Latin-1 gibberish where Arabic belongs."""
    if _REPLACEMENT in value:
        return True
    normalized = normalize_text(value)
    if has_arabic(normalized):
        return False
    # Arabic misdecoded as Latin-1 produces runs from the C1/Latin-1 supplement
    # block. Plain ASCII is fine — a supplier may legitimately have a Latin name.
    suspicious = sum(1 for ch in value if 0x80 <= ord(ch) <= 0x24F)
    return suspicious >= max(2, len(value) // 3)


def _encoding_finding(key: str, kind: str, value: str = "") -> RuleResult:
    if kind == "empty":
        return failure(
            "ARABIC_ENCODING_SUSPECT",
            message_ar=(
                f"المستند يعرض نصاً عربياً، إلا أن الحقل «{key}» في ملف XML المرفق "
                f"فارغ. يُرجّح وجود خلل في ترميز النص لدى نظام المورّد."
            ),
            message_en=(
                f"The document renders Arabic, but field '{key}' in the embedded XML "
                f"is empty. This usually indicates an encoding fault in the "
                f"supplier's e-invoicing system."
            ),
            field_key=key,
        )
    return failure(
        "ARABIC_ENCODING_SUSPECT",
        message_ar=(
            f"المستند يعرض نصاً عربياً، إلا أن قيمة الحقل «{key}» في ملف XML "
            f"المرفق تبدو تالفة الترميز («{value[:40]}»)."
        ),
        message_en=(
            f"The document renders Arabic, but field '{key}' in the embedded XML "
            f"looks mis-encoded ('{value[:40]}')."
        ),
        field_key=key,
    )


MIN_ARABIC_TOKENS_TO_JUDGE = 20
"""Fewer than this and a few short words would decide the verdict."""

SHATTERED_SINGLE_LETTER_SHARE = 0.25
"""Real Arabic has a few one-letter words. A quarter of them is not real."""

ARTICLE_SHARE_OF_REAL_TEXT = 0.05
"""In ordinary Arabic well over 5% of tokens begin with the definite article."""


@rule(
    "TEXT_LAYER_FRAGMENTED",
    Severity.WARNING,
    message_ar="نص الصفحة العربي مجزّأ إلى أحرف منفصلة، وقد لا تكون القراءة موثوقة.",
    message_en="The page's Arabic text is split into fragments, so this reading may be unreliable.",
)
def text_layer_is_intact(ctx: ValidationContext) -> list[RuleResult] | None:
    """Detect a text layer whose Arabic words have been cut apart.

    Found on the first real invoice: the layer split words after non-joining
    letters, so 40% of its Arabic tokens were single letters and none began with
    the definite article. A language model handed that text loses its own field
    labels and either returns null or mixes one party's value into another's,
    with no sign that anything went wrong. This is the sign.

    Both signatures are required, because either alone occurs in healthy text.
    """
    tokens = [t for t in ctx.page_text.split() if has_arabic(t)]
    if len(tokens) < MIN_ARABIC_TOKENS_TO_JUDGE:
        return None
    single = sum(1 for t in tokens if len(t) == 1) / len(tokens)
    article = sum(1 for t in tokens if t.startswith("ال")) / len(tokens)
    if single < SHATTERED_SINGLE_LETTER_SHARE or article >= ARTICLE_SHARE_OF_REAL_TEXT:
        return []
    return [
        failure(
            "TEXT_LAYER_FRAGMENTED",
            message_ar=(
                f"{single:.0%} من الكلمات العربية في نص الصفحة حرف واحد، ولا توجد كلمات "
                "تبدأ بأداة التعريف؛ يبدو أن الكلمات مقطّعة. راجع الحقول مع الصفحة."
            ),
            message_en=(
                f"{single:.0%} of the page's Arabic words are single letters and none "
                "begin with the definite article: the words look cut apart. Check the "
                "fields against the page."
            ),
        )
    ]
