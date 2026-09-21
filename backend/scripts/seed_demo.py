"""Seed a demo tenant: org, queue, and a bilingual extraction schema.

The extraction schema is the point. The field list lives in a database row and
is read at request time, so adding a field is a row edit rather than a retrain.
Nothing in the codebase hardcodes these keys.

    backend/.venv/Scripts/python.exe -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sql

from app.db.base import get_sessionmaker

DEMO_ORG_NAME = "Munsiq Demo — منسق للعرض"

# The name this organization was first seeded under, with the app name misspelt
# (منصق for منسق). The organization is found BY NAME, so without this a
# database seeded before the fix would get a second demo organization and lose
# its documents. It is renamed in place instead, keeping its id, which is what
# MUNSIQ_ORG_ID points at.
MISSPELT_DEMO_ORG_NAME = "Munsiq Demo — منصق للعرض"

INVOICE_SCHEMA: dict[str, object] = {
    "name": "Saudi tax invoice",
    "fields": [
        {
            "key": "invoice_number",
            "type": "string",
            "label_en": "Invoice number",
            "label_ar": "رقم الفاتورة",
            "required": True,
            "confidence_threshold": 0.9,
            "guideline": (
                "The supplier's own invoice reference, usually near the top and "
                "labelled Invoice No / رقم الفاتورة. Not the purchase order number, "
                "not the ICV counter."
            ),
        },
        {
            "key": "issue_date",
            "type": "date",
            "label_en": "Issue date",
            "label_ar": "تاريخ الإصدار",
            "synonyms": ["Date", "Invoice date", "التاريخ", "تاريخ الفاتورة"],
            "required": True,
            "confidence_threshold": 0.9,
            "guideline": (
                "The date the invoice was issued. Copy it exactly as printed — do "
                "not convert between Hijri and Gregorian. If both appear, take the "
                "Gregorian one."
            ),
        },
        {
            "key": "seller_name",
            "type": "string",
            "label_en": "Seller name",
            "label_ar": "اسم البائع",
            "synonyms": ["Seller", "Supplier", "Sold by", "البائع", "المورد"],
            "required": True,
            "confidence_threshold": 0.85,
            "guideline": "Legal name of the supplier issuing the invoice.",
        },
        {
            "key": "seller_trn",
            "type": "string",
            "label_en": "Seller VAT number",
            "label_ar": "الرقم الضريبي للبائع",
            "required": True,
            "confidence_threshold": 0.95,
            "guideline": (
                "The supplier's 15-digit VAT registration number. Starts with 3 and "
                "ends with 3. Do not confuse it with the CR (commercial "
                "registration) number, which is 10 digits."
            ),
        },
        {
            "key": "buyer_name",
            "type": "string",
            "label_en": "Buyer name",
            "label_ar": "اسم المشتري",
            "synonyms": [
                "Buyer",
                "Customer",
                "Bill to",
                "Sold to",
                "المشتري",
                "العميل",
                "اسم العميل",
            ],
            "required": False,
            "confidence_threshold": 0.85,
            "guideline": "Legal name of the customer being invoiced.",
        },
        {
            "key": "buyer_trn",
            "type": "string",
            "label_en": "Buyer VAT number",
            "label_ar": "الرقم الضريبي للمشتري",
            "required": False,
            "confidence_threshold": 0.95,
            "guideline": (
                "The buyer's 15-digit VAT number. Often absent on simplified "
                "invoices — return null when it is not printed."
            ),
        },
        {
            "key": "subtotal",
            "type": "decimal",
            "label_en": "Subtotal (excl. VAT)",
            "label_ar": "المجموع قبل الضريبة",
            "synonyms": [
                "Subtotal",
                "Total before VAT",
                "Taxable amount",
                "المجموع الفرعي",
                "الإجمالي قبل الضريبة",
                "المبلغ الخاضع للضريبة",
            ],
            "required": True,
            "confidence_threshold": 0.9,
            "guideline": (
                "The amount EXCLUDING VAT: the taxable amount, before any tax is added. "
                "If the document states only ONE amount and it is a tax-inclusive total "
                "(for example a purchase summary, or a line such as 'total including "
                "VAT'), the subtotal is null — never copy the total into it. "
                "Digits only, keep the decimal point."
            ),
        },
        {
            "key": "vat_amount",
            "type": "decimal",
            "label_en": "VAT amount",
            "label_ar": "مبلغ ضريبة القيمة المضافة",
            "required": True,
            "confidence_threshold": 0.9,
            "guideline": "The VAT charged, usually 15% of the subtotal.",
        },
        {
            "key": "total_amount",
            "type": "decimal",
            "label_en": "Total (incl. VAT)",
            "label_ar": "الإجمالي شامل الضريبة",
            "synonyms": [
                "Grand total",
                "Total due",
                "Amount due",
                "الإجمالي المستحق",
                "المجموع الكلي",
            ],
            "required": True,
            "confidence_threshold": 0.9,
            "guideline": "Grand total payable, INCLUDING VAT. Digits only, keep the decimal point.",
        },
        {
            "key": "currency",
            "type": "string",
            "label_en": "Currency",
            "label_ar": "العملة",
            "required": False,
            "confidence_threshold": 0.8,
            "guideline": "ISO code, e.g. SAR. Default to SAR if only ر.س is shown.",
        },
        {
            "key": "purchase_order_number",
            "type": "string",
            "label_en": "Purchase order number",
            "label_ar": "رقم أمر الشراء",
            "synonyms": ["Purchase order", "PO number", "أمر شراء"],
            "required": False,
            "confidence_threshold": 0.8,
            "guideline": (
                "The buyer's PO/LPO reference if the invoice quotes one. Frequently "
                "absent — return null rather than guessing."
            ),
        },
    ],
    # A repeating group, one set of rows per invoice line. Populated from the
    # signed UBL on the Step Zero path; the model prompt never sees it.
    "line_item_fields": [
        {
            "key": "line_description",
            "type": "string",
            "label_en": "Description",
            "label_ar": "الوصف",
        },
        {
            "key": "line_quantity",
            "type": "decimal",
            "label_en": "Quantity",
            "label_ar": "الكمية",
        },
        {
            "key": "line_unit_price",
            "type": "decimal",
            "label_en": "Unit price",
            "label_ar": "سعر الوحدة",
        },
        {
            "key": "line_amount",
            "type": "decimal",
            "label_en": "Line amount (excl. VAT)",
            "label_ar": "مبلغ البند قبل الضريبة",
        },
    ],
}

FIELD_COUNT = len(cast("list[object]", INVOICE_SCHEMA["fields"]))


async def main() -> int:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        renamed = await session.scalar(
            sql(
                "UPDATE organizations SET name = :new WHERE name = :old "
                "AND NOT EXISTS (SELECT 1 FROM organizations WHERE name = :new) "
                "RETURNING id"
            ),
            {"new": DEMO_ORG_NAME, "old": MISSPELT_DEMO_ORG_NAME},
        )
        if renamed is not None:
            print(f"renamed organization {renamed} to {DEMO_ORG_NAME!r}")
        org_id = await session.scalar(
            sql("SELECT id FROM organizations WHERE name = :n"), {"n": DEMO_ORG_NAME}
        )
        if org_id is None:
            org_id = uuid.uuid4()
            await session.execute(
                sql(
                    "INSERT INTO organizations (id, name, vat_number) "
                    "VALUES (:id, :n, '310122393510003')"
                ),
                {"id": org_id, "n": DEMO_ORG_NAME},
            )
            print(f"created organization {org_id}")
        else:
            print(f"organization exists {org_id}")

        queue_id = await session.scalar(
            sql("SELECT id FROM queues WHERE org_id = :o ORDER BY created_at LIMIT 1"),
            {"o": org_id},
        )
        if queue_id is None:
            queue_id = uuid.uuid4()
            await session.execute(
                sql("INSERT INTO queues (id, org_id, name) VALUES (:id, :o, 'Accounts Payable')"),
                {"id": queue_id, "o": org_id},
            )
            print(f"created queue {queue_id}")

        latest = (
            await session.execute(
                sql(
                    "SELECT id, version, definition FROM extraction_schemas "
                    "WHERE queue_id = :q ORDER BY version DESC LIMIT 1"
                ),
                {"q": queue_id},
            )
        ).first()
        # Re-running must not mint a version per run: a version is a claim that the
        # definition CHANGED, and the Templates page lists every one of them.
        if latest is not None and latest.definition == INVOICE_SCHEMA:
            schema_id, version = latest.id, latest.version
            print(f"extraction schema v{version} is current ({FIELD_COUNT} fields)")
        else:
            version = (latest.version if latest else 0) + 1
            schema_id = uuid.uuid4()
            await session.execute(
                sql(
                    "INSERT INTO extraction_schemas (id, org_id, queue_id, version, definition) "
                    "VALUES (:id, :o, :q, :v, CAST(:d AS jsonb))"
                ),
                {
                    "id": schema_id,
                    "o": org_id,
                    "q": queue_id,
                    "v": version,
                    "d": json.dumps(INVOICE_SCHEMA, ensure_ascii=False),
                },
            )
            print(f"created extraction schema v{version} ({FIELD_COUNT} fields)")
        await session.execute(
            sql("UPDATE queues SET active_schema_id = :s WHERE id = :q"),
            {"s": schema_id, "q": queue_id},
        )

    print()
    print("ORG_ID for API calls:", org_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
