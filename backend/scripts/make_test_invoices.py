"""Generate six varied test invoices for manual upload testing.

    backend/.venv/Scripts/python.exe -m scripts.make_test_invoices

Writes to samples/test/ (git-ignored) and DOES NOT PROCESS THEM. Nothing here
touches the database, storage or the model: upload the files through the UI and
watch what happens. What each one should do is printed at the end, and it is
computed, not guessed — the script dry-runs the deterministic stages (Step Zero,
text-layer reading, grounding, the rules engine) on the files it just wrote.

  1  UBL, English      compliant; the model is never called
  2  UBL, Arabic       compliant; Arabic page, Arabic names in the signed XML
  3  digital, English  no attachment; the model reads a clean invoice
  4  digital, Arabic   no attachment; the model reads an Arabic invoice
  5  arithmetic error  no attachment; the printed VAT is not 15% of the subtotal
  6  invalid TRN       no attachment; the seller's VAT number fails the format check

CAVEAT, inherited from tests/fixtures.py: the UBL is ZATCA-*shaped* and built with
the same library that reads it back. It proves this codebase is self-consistent,
not that it can read the output of ZATCA-certified e-invoicing software. The
signatures in it are placeholders and are never verified. Only a real sample
proves that — see samples/README.md.

All names, numbers and VAT registrations are invented.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
from pypdf import PdfReader, PdfWriter

from app.services.extraction.grounding import ground_value
from app.services.extraction.prompts import parse_schema
from app.services.extraction.runner import ExtractedValue
from app.services.pagetext import extract_page_text
from app.services.ubl import extract_embedded_xml, parse_ubl_invoice, validate_trn
from app.services.validation import run_rules
from app.services.validation.context import build_context
from scripts.seed_demo import INVOICE_SCHEMA
from tests.fixtures import build_tlv

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "samples" / "test"

FONT_DIR = Path(r"C:\Windows\Fonts")
LATIN_FONT = FONT_DIR / "arial.ttf"
CENT = Decimal("0.01")
VAT_RATE = Decimal("0.15")

# Well-formed TRNs: 15 digits, leading 3, trailing 3. (There is no published
# checksum to satisfy beyond that — see app/services/ubl.py, validate_trn.)
BUYER_TRN = "311111111110003"
INVALID_TRN = "300987654300004"  # ends in 4, not 3 — fails the format check


# --------------------------------------------------------------------------- #
# The invoices
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Line:
    description: str
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(CENT)


@dataclass(frozen=True)
class Invoice:
    filename: str
    kind: str
    number: str
    date: str
    seller: str
    seller_trn: str
    buyer: str
    buyer_trn: str
    lines: tuple[Line, ...]
    arabic: bool = False
    embed_ubl: bool = False
    po_number: str | None = None
    # What the page PRINTS for VAT, when it is deliberately wrong.
    printed_vat: Decimal | None = None

    @property
    def subtotal(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0.00"))

    @property
    def vat(self) -> Decimal:
        if self.printed_vat is not None:
            return self.printed_vat
        return (self.subtotal * VAT_RATE).quantize(CENT, rounding=ROUND_HALF_UP)

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.vat


def d(value: str) -> Decimal:
    return Decimal(value)


INVOICES: tuple[Invoice, ...] = (
    Invoice(
        filename="01_ubl_english_compliant.pdf",
        kind="UBL · English",
        number="INV-2026-1041",
        date="2026-04-06",
        seller="Gulf Coast Valve & Pipe Trading Co.",
        seller_trn="300456782110003",
        buyer="Jubail Maintenance Services Ltd.",
        buyer_trn=BUYER_TRN,
        lines=(
            Line("Gate valve 4 inch DN100", 6, d("850.00")),
            Line("Flanged check valve 6 inch", 4, d("1975.00")),
            Line("PTFE gasket set", 20, d("42.50")),
        ),
        embed_ubl=True,
    ),
    Invoice(
        filename="02_ubl_arabic_primary.pdf",
        kind="UBL · Arabic",
        number="ARB-2026-0211",
        date="2026-04-09",
        seller="شركة النخبة للتجهيزات الصناعية",
        seller_trn="300712345610003",
        buyer="مؤسسة الخليج للمقاولات",
        buyer_trn="311222333310003",
        lines=(
            Line("مضخة غاطسة 2 حصان", 3, d("4200.00")),
            Line("كابل كهربائي 4 × 16 مم", 150, d("38.00")),
            Line("لوحة تحكم كهربائية", 1, d("9400.00")),
        ),
        arabic=True,
        embed_ubl=True,
    ),
    Invoice(
        filename="03_digital_english_no_ubl.pdf",
        kind="digital · English",
        number="ROE-2026-3306",
        date="2026-04-12",
        seller="Riyadh Office Equipment Co.",
        seller_trn="300234567810003",
        buyer="Al Rajhi Contracting Co.",
        buyer_trn="311555666610003",
        lines=(
            Line("Ergonomic office chair", 12, d("640.00")),
            Line("Height-adjustable desk", 6, d("1450.00")),
        ),
        po_number="PO-88213",
    ),
    Invoice(
        filename="04_digital_arabic_no_ubl.pdf",
        kind="digital · Arabic",
        number="RS-2026-0562",
        date="2026-04-14",
        seller="مؤسسة الرياض لقطع الغيار",
        seller_trn="300345678910003",
        buyer="شركة الجبيل للصيانة",
        buyer_trn="311777888810003",
        lines=(
            Line("فلتر زيت", 40, d("55.00")),
            Line("سير محرك", 10, d("120.00")),
        ),
        arabic=True,
    ),
    Invoice(
        filename="05_arithmetic_error.pdf",
        kind="arithmetic error",
        number="DIS-2026-0919",
        date="2026-04-16",
        seller="Dammam Industrial Supplies Est.",
        seller_trn="300567890110003",
        buyer="Jubail Maintenance Services Ltd.",
        buyer_trn=BUYER_TRN,
        lines=(
            Line("Hydraulic hose 2 inch", 8, d("310.00")),
            Line("Quick coupling set", 5, d("720.00")),
            Line("Pressure gauge", 12, d("95.00")),
        ),
        # 15% of 7,220.00 is 1,083.00. The page says 1,380.00 — digits scrambled —
        # and the total was added up from THAT, so the sum is self-consistent and
        # only the VAT line is wrong.
        printed_vat=d("1380.00"),
    ),
    Invoice(
        filename="06_invalid_trn.pdf",
        kind="invalid TRN",
        number="KCE-2026-0447",
        date="2026-04-18",
        seller="Khobar Cable & Electrical Co.",
        seller_trn=INVALID_TRN,
        buyer="Al Rajhi Contracting Co.",
        buyer_trn="311555666610003",
        lines=(
            Line("Armoured cable 3x95 mm (per metre)", 200, d("118.00")),
            Line("Cable gland M32", 40, d("15.00")),
        ),
    ),
)


def money(value: Decimal) -> str:
    """52118.00 -> '52,118.00', the way a supplier's system prints it."""
    return f"{value:,.2f}"


# --------------------------------------------------------------------------- #
# The signed UBL attachment (ZATCA-shaped)
# --------------------------------------------------------------------------- #
def build_ubl(inv: Invoice) -> bytes:
    qr = base64.b64encode(
        build_tlv(
            {
                1: inv.seller.encode("utf-8"),
                2: inv.seller_trn.encode("utf-8"),
                3: f"{inv.date}T09:20:00Z".encode(),
                4: f"{inv.total:.2f}".encode(),
                5: f"{inv.vat:.2f}".encode(),
                # Placeholders shaped like the Phase 2 cryptographic tags. Never verified.
                6: bytes(range(32)),
                7: bytes(range(64)),
                8: bytes(range(77)),
                9: bytes(range(64)),
            }
        )
    ).decode("ascii")

    lines = "".join(
        f"""
  <cac:InvoiceLine>
    <cbc:ID>{index}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="PCE">{line.quantity}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="SAR">{line.amount:.2f}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>{escape(line.description)}</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="SAR">{line.unit_price:.2f}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>"""
        for index, line in enumerate(inv.lines, start=1)
    )

    def party(name: str, trn: str, city: str) -> str:
        return f"""
    <cac:Party>
      <cac:PostalAddress>
        <cbc:CityName>{escape(city)}</cbc:CityName>
        <cac:Country><cbc:IdentificationCode>SA</cbc:IdentificationCode></cac:Country>
      </cac:PostalAddress>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{trn}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>{escape(name)}</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>"""

    cities = ("الدمام", "الجبيل") if inv.arabic else ("Dammam", "Jubail")
    uuid_value = uuid.uuid5(uuid.NAMESPACE_URL, f"munsiq-test/{inv.number}")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ProfileID>reporting:1.0</cbc:ProfileID>
  <cbc:ID>{inv.number}</cbc:ID>
  <cbc:UUID>{uuid_value}</cbc:UUID>
  <cbc:IssueDate>{inv.date}</cbc:IssueDate>
  <cbc:IssueTime>09:20:00</cbc:IssueTime>
  <cbc:InvoiceTypeCode name="0100000">388</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>
  <cbc:TaxCurrencyCode>SAR</cbc:TaxCurrencyCode>
  <cac:AdditionalDocumentReference><cbc:ID>ICV</cbc:ID><cbc:UUID>23</cbc:UUID></cac:AdditionalDocumentReference>
  <cac:AdditionalDocumentReference>
    <cbc:ID>PIH</cbc:ID>
    <cac:Attachment><cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzk=</cbc:EmbeddedDocumentBinaryObject></cac:Attachment>
  </cac:AdditionalDocumentReference>
  <cac:AdditionalDocumentReference>
    <cbc:ID>QR</cbc:ID>
    <cac:Attachment><cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">{qr}</cbc:EmbeddedDocumentBinaryObject></cac:Attachment>
  </cac:AdditionalDocumentReference>
  <cac:AccountingSupplierParty>{party(inv.seller, inv.seller_trn, cities[0])}
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>{party(inv.buyer, inv.buyer_trn, cities[1])}
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="SAR">{inv.vat:.2f}</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="SAR">{inv.subtotal:.2f}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="SAR">{inv.vat:.2f}</cbc:TaxAmount>
      <cac:TaxCategory>
        <cbc:ID>S</cbc:ID>
        <cbc:Percent>15.00</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="SAR">{inv.subtotal:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="SAR">{inv.subtotal:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="SAR">{inv.total:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="SAR">{inv.total:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>{lines}
</Invoice>
""".encode()


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #
def render_english(inv: Invoice) -> bytes:
    """A digital invoice: real text-layer text at fixed columns, in Arial."""
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=595, height=842)
    font = pymupdf.Font(fontfile=str(LATIN_FONT))

    def put(x: float, y: float, text: str, size: float = 11, *, right: bool = False) -> None:
        origin = x - font.text_length(text, fontsize=size) if right else x
        page.insert_text((origin, y), text, fontsize=size, fontname="ar", fontfile=str(LATIN_FONT))

    put(60, 84, "TAX INVOICE", 20)
    put(60, 116, f"Invoice No: {inv.number}")
    put(60, 133, f"Issue Date: {inv.date}")
    if inv.po_number:
        put(60, 150, f"PO No: {inv.po_number}")

    put(60, 186, f"Seller: {inv.seller}")
    put(60, 203, f"VAT No: {inv.seller_trn}")
    put(60, 232, f"Buyer: {inv.buyer}")
    put(60, 249, f"VAT No: {inv.buyer_trn}")

    y = 292
    put(60, y, "Description", 10)
    put(340, y, "Qty", 10, right=True)
    put(430, y, "Unit price", 10, right=True)
    put(535, y, "Amount", 10, right=True)
    page.draw_line((60, y + 6), (535, y + 6), color=(0.6, 0.6, 0.6), width=0.5)
    y += 24
    for line in inv.lines:
        put(60, y, line.description)
        put(340, y, str(line.quantity), right=True)
        put(430, y, money(line.unit_price), right=True)
        put(535, y, money(line.amount), right=True)
        y += 20

    y += 18
    put(430, y, "Subtotal (excl. VAT):", 11, right=True)
    put(535, y, money(inv.subtotal), right=True)
    put(430, y + 20, "VAT 15%:", 11, right=True)
    put(535, y + 20, money(inv.vat), right=True)
    put(430, y + 44, "Total (incl. VAT):", 13, right=True)
    put(535, y + 44, f"{money(inv.total)} SAR", 13, right=True)

    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return buffer.getvalue()


def render_arabic(inv: Invoice) -> bytes:
    """An Arabic-primary invoice, shaped and laid out right to left.

    MuPDF's HTML engine does the shaping, so the text layer holds Arabic
    presentation forms with non-breaking spaces — what real Arabic PDFs contain
    and what naive extraction chokes on. The pipeline normalizes them back.
    """
    rows = "".join(
        f"<tr><td>{line.description}</td><td class='n'>{line.quantity}</td>"
        f"<td class='n'>{money(line.unit_price)}</td><td class='n'>{money(line.amount)}</td></tr>"
        for line in inv.lines
    )
    po = f"<p>رقم أمر الشراء: {inv.po_number}</p>" if inv.po_number else ""
    html = f"""<body>
<h2>فاتورة ضريبية</h2>
<p>رقم الفاتورة: {inv.number}</p>
<p>تاريخ الإصدار: {inv.date}</p>
{po}
<p>البائع: {inv.seller}</p>
<p>الرقم الضريبي للبائع: {inv.seller_trn}</p>
<p>المشتري: {inv.buyer}</p>
<p>الرقم الضريبي للمشتري: {inv.buyer_trn}</p>
<table>
<tr><th>البيان</th><th>الكمية</th><th>سعر الوحدة</th><th>المبلغ</th></tr>
{rows}
</table>
<p>المجموع قبل الضريبة: {money(inv.subtotal)}</p>
<p>ضريبة القيمة المضافة 15%: {money(inv.vat)}</p>
<p><b>الإجمالي شامل الضريبة: {money(inv.total)} ريال</b></p>
</body>"""
    css = f"""
@font-face {{ font-family: ArabicFace; src: url({LATIN_FONT.name}); }}
body {{ font-family: ArabicFace; font-size: 11pt; direction: rtl; text-align: right; }}
h2 {{ font-size: 20pt; margin: 0 0 14pt 0; }}
p {{ margin: 0 0 5pt 0; }}
table {{ width: 100%; margin: 14pt 0; border-collapse: collapse; }}
th, td {{ padding: 4pt; border-bottom: 0.5pt solid #999; }}
th {{ font-size: 10pt; }}
.n {{ text-align: left; }}
"""
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=595, height=842)
    spare, _ = page.insert_htmlbox(
        pymupdf.Rect(60, 60, 535, 780), html, css=css, archive=pymupdf.Archive(str(FONT_DIR))
    )
    if spare < 0:
        raise SystemExit(f"{inv.filename}: the Arabic layout did not fit on the page")
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return buffer.getvalue()


def build_pdf(inv: Invoice) -> bytes:
    page = render_arabic(inv) if inv.arabic else render_english(inv)
    if not inv.embed_ubl:
        return page
    writer = PdfWriter()
    for rendered in PdfReader(io.BytesIO(page)).pages:
        writer.add_page(rendered)
    writer.add_attachment("invoice.xml", build_ubl(inv))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def expected_values(inv: Invoice) -> dict[str, str | None]:
    """What a perfect reader would return for this invoice, field by field.

    The page and these numbers come from the same object, so they agree by
    construction. ``None`` means the field is genuinely not on the page, which is
    also something a reader can get wrong (by inventing one).
    """
    return {
        "invoice_number": inv.number,
        "issue_date": inv.date,
        "seller_name": inv.seller,
        "seller_trn": inv.seller_trn,
        "buyer_name": inv.buyer,
        "buyer_trn": inv.buyer_trn,
        "subtotal": f"{inv.subtotal:.2f}",
        "vat_amount": f"{inv.vat:.2f}",
        "total_amount": f"{inv.total:.2f}",
        "currency": "SAR",
        "purchase_order_number": inv.po_number,
    }


# --------------------------------------------------------------------------- #
# The dry run: the deterministic stages only. No database, no storage, no model.
# --------------------------------------------------------------------------- #
@dataclass
class Prediction:
    blockers: list[str]
    warnings: list[str]
    grounded: str
    note: str


def predict(inv: Invoice, pdf: bytes) -> Prediction:
    fields = parse_schema(INVOICE_SCHEMA)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        pages = [extract_page_text(page, index) for index, page in enumerate(doc, start=1)]

    ubl_invoice = None
    if inv.embed_ubl:
        xml = extract_embedded_xml(pdf)
        if xml is None:
            raise SystemExit(f"{inv.filename}: the UBL attachment could not be read back")
        ubl_invoice = parse_ubl_invoice(xml)
        values = {k: f.value for k, f in ubl_invoice.to_extracted_fields().items() if f.value}
        source, note = "ubl_xml", "Step Zero reads the signed XML; the model is never called."
    else:
        # What the page prints. A prediction, ASSUMING the model reads it correctly.
        values = {k: v for k, v in expected_values(inv).items() if v is not None}
        source = "vlm"
        note = "No attachment: the model runs. Rules predicted from the printed values."

    extracted = [
        ExtractedValue(
            field_key=spec.key,
            value=values.get(spec.key),
            source=source if spec.key in values else "ocr_rule",
            confidence=1.0 if spec.key in values else 0.0,
            validation_state="auto_validated",
        )
        for spec in fields
    ]
    context = build_context(values=extracted, fields=fields, pages=pages, invoice=ubl_invoice)
    report = run_rules(context)

    failing = [r for r in report.results if not r.passed]
    boxed = sum(1 for v in extracted if v.value and ground_value(v.value, pages).bbox is not None)
    present = sum(1 for v in extracted if v.value)
    return Prediction(
        blockers=sorted(
            {
                f"{r.code}({r.field_key})" if r.field_key else r.code
                for r in failing
                if r.severity.value == "error"
            }
        ),
        warnings=sorted({r.code for r in failing if r.severity.value == "warning"}),
        grounded=f"{boxed}/{present}",
        note=note,
    )


def generate(out_dir: Path) -> list[tuple[Invoice, bytes, Prediction]]:
    """Write every invoice to ``out_dir`` and predict what each should trigger."""
    if not LATIN_FONT.exists():
        raise SystemExit(f"{LATIN_FONT} not found: this script needs Arial (Arabic glyphs).")
    for inv in INVOICES:
        for trn in (inv.seller_trn, inv.buyer_trn):
            expected_valid = trn != INVALID_TRN
            if validate_trn(trn) != expected_valid:
                verdict = "valid" if expected_valid else "invalid"
                raise SystemExit(f"{inv.filename}: TRN {trn} is not {verdict}")

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for inv in INVOICES:
        pdf = build_pdf(inv)
        (out_dir / inv.filename).write_bytes(pdf)
        results.append((inv, pdf, predict(inv, pdf)))
    # Ground truth for scripts/benchmark.py. Lives beside the PDFs, so it is
    # git-ignored with them, and it is invented data like everything else here.
    (out_dir / "expected.json").write_text(
        json.dumps(
            {inv.filename: expected_values(inv) for inv in INVOICES}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    return results


def main() -> int:
    print(f"Writing to {OUT_DIR}")
    for inv, pdf, result in generate(OUT_DIR):
        print()
        print(f"{inv.filename}   [{inv.kind}]   {len(pdf) / 1024:.0f} KB")
        print(
            f"  invoice {inv.number}   total {money(inv.total)} SAR   "
            f"({inv.subtotal:,.2f} + VAT {money(inv.vat)})"
        )
        print(f"  blockers : {', '.join(result.blockers) or 'none'}")
        print(f"  warnings : {', '.join(result.warnings) or 'none'}")
        print(f"  grounded : {result.grounded} values have a box on the page")
        print(f"  {result.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
