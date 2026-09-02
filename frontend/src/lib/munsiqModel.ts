// Shared extraction logic used by both the single-shot /api/extract route and
// the batch /api/invoices/upload route -- one prompt/model-call definition, not two.
//
// Model: qwen2.5:7b-instruct (stock Ollama pull, chat-tuned). We deliberately do NOT
// use the fine-tuned `munsiq-extractor` model here -- it was trained via raw completion
// on a fixed 5-field schema, so it resists producing arbitrary keys no matter how the
// prompt is written. A general instruct model + Ollama's JSON grammar mode (`format:
// "json"`, which guarantees syntactically valid JSON but does NOT constrain which keys
// appear) is what actually makes per-document, variable-shape extraction possible.

const OLLAMA_CHAT_URL = "http://localhost:11434/api/chat";
export const MODEL_NAME = "qwen2.5:7b-instruct";

// Line items + a variable number of header fields need more headroom than a fixed
// 5-field object did. Raised well past the old 384-token cap for fixed-schema output.
export const MAX_PREDICT_TOKENS = 1536;

// Tuned for a 4GB VRAM card, same spirit as the old Modelfile's num_gpu/num_thread --
// but passed per-request now since we're calling the stock pulled model directly
// rather than baking a custom Modelfile on top of it.
const MODEL_OPTIONS = {
  temperature: 0.1,
  num_predict: MAX_PREDICT_TOKENS,
  num_ctx: 4096,
  num_gpu: 15,
  num_thread: 6,
};

export const SYSTEM_PROMPT = `أنت محرك استخراج بيانات خبير لمستندات الأعمال الصناعية (فواتير، أوامر شراء، عقود، تقارير صيانة، إلخ).

مهمتك: قراءة النص المرفق وإرجاع كائن JSON واحد فقط يعكس البيانات الفعلية الموجودة في هذا المستند بالذات -- وليس مطابقة مستند لمخطط ثابت مسبق.

القواعد:
1. لا يوجد مخطط ثابت. مفاتيح الـ JSON (keys) يجب أن تُشتق من محتوى المستند نفسه: مستند فيه شرائح ضريبية متعددة، خصومات، رقم IBAN، أو شروط دفع يجب أن تظهر هذه كمفاتيح منفصلة؛ مستند بسيط لا يحتوي عليها لا يجب أن يتضمنها.
2. استخدم أسماء مفاتيح بصيغة snake_case بالإنجليزية دائماً (مثال: vendor_name, invoice_number, iban, vat_rate_percent, payment_terms)، حتى لو كانت القيم بالعربية.
3. لا تخترع بيانات غير موجودة في النص. إن لم يوجد حقل في المستند، لا تُدرجه إطلاقاً في الناتج (لا تضع null ولا نص فارغ).
4. انسخ التواريخ والأرقام والمعرفات (IBAN، رقم الفاتورة...) حرفياً كما وردت، دون إعادة تنسيق.
5. إن وجد جدول بنود متعددة (أصناف/خدمات)، ضعها في مصفوفة باسم "line_items" حيث كل عنصر كائن JSON مفاتيحه مطابقة لأعمدة الجدول الفعلية في المستند (قد تختلف هذه المفاتيح من مستند لآخر).
6. أعد كائن JSON صالح واحد فقط. بدون أي شرح أو تعليق أو Markdown code fences.

مثال (للتوضيح فقط -- لا تنسخ هذه القيم، هي فقط لإظهار المرونة المطلوبة في المفاتيح):
{
  "document_type": "Invoice",
  "vendor_name": "شركة الخليج للمعدات",
  "invoice_number": "INV-2024-118",
  "invoice_date": "14/03/2024",
  "iban": "SA1234567890123456789012",
  "subtotal_sar": 12000,
  "vat_rate_percent": 15,
  "vat_amount_sar": 1800,
  "discount_sar": 500,
  "total_sar": 13300,
  "line_items": [
    { "description": "مضخة هيدروليكية", "quantity": 2, "unit_price_sar": 4000, "total_sar": 8000 },
    { "description": "صيانة دورية", "quantity": 1, "unit_price_sar": 4000, "total_sar": 4000 }
  ]
}

مستند آخر بدون IBAN أو خصم أو بنود متعددة قد ينتج فقط: document_type, vendor_name, total_sar, critical_date -- ولا شيء غير موجود فعلياً في النص.`;

export function buildMessages(contractText: string) {
  return [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: contractText },
  ];
}

// A single line item row: keys vary per document, values are kept to JSON primitives
// (arrays/objects from the model get flattened -- see normalizeExtraction).
export type FieldValue = string | number | boolean | null;
export type LineItem = Record<string, FieldValue>;

export interface DynamicExtraction {
  fields: Record<string, FieldValue>;
  lineItems: LineItem[];
}

function flattenToPrimitive(value: unknown): FieldValue {
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((v) => (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v))).join("; ");
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// The model is asked for "line_items" but instruct models occasionally use a close
// synonym -- accept the common variants rather than silently dropping the array.
const LINE_ITEM_KEYS = ["line_items", "items", "lineItems"];

/**
 * Splits the model's raw JSON object into flat header fields vs. the line-item table.
 * Tolerant by design: any top-level key that isn't a recognized line-item array becomes
 * a scalar field (objects/arrays get flattened rather than rejected), since a stricter
 * parser would defeat the point of letting the schema vary per document.
 */
function normalizeExtraction(raw: Record<string, unknown>): DynamicExtraction {
  const fields: Record<string, FieldValue> = {};
  let lineItems: LineItem[] = [];

  for (const [key, value] of Object.entries(raw)) {
    if (LINE_ITEM_KEYS.includes(key) && Array.isArray(value)) {
      lineItems = value
        .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
        .map((item) => {
          const row: LineItem = {};
          for (const [k, v] of Object.entries(item)) row[k] = flattenToPrimitive(v);
          return row;
        });
      continue;
    }
    fields[key] = flattenToPrimitive(value);
  }

  return { fields, lineItems };
}

function parseJsonBlock(text: string): DynamicExtraction | null {
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const raw = JSON.parse(match[0]);
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
    return normalizeExtraction(raw);
  } catch {
    return null;
  }
}

function tryParseNdjsonLine(line: string): { message?: { content?: string }; done_reason?: string } | null {
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}

export interface ExtractionResult {
  raw: string;
  parsed: DynamicExtraction | null;
  // True when generation stopped because it hit num_predict rather than the
  // model's own stop token -- a likely cause of an incomplete/malformed JSON
  // object, and worth surfacing separately from "the model produced garbage".
  truncated: boolean;
}

/**
 * Streams a chat completion from the local Ollama endpoint and reports progress
 * based on tokens actually received so far vs. the requested max -- real
 * signal from the running model, not a simulated timer.
 *
 * Always resolves or throws a plain Error with a readable message -- callers
 * can rely on try/catch without worrying about non-Error rejections or a
 * malformed NDJSON line crashing the whole extraction.
 */
export async function extractFromText(
  text: string,
  onProgress?: (pct: number) => void,
): Promise<ExtractionResult> {
  let response: Response;
  try {
    response = await fetch(OLLAMA_CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL_NAME,
        messages: buildMessages(text),
        format: "json",
        stream: true,
        options: MODEL_OPTIONS,
      }),
    });
  } catch (err) {
    throw new Error(
      `Could not reach Ollama at localhost:11434 -- is it running? (${
        err instanceof Error ? err.message : "unknown error"
      })`,
    );
  }

  if (!response.ok || !response.body) {
    throw new Error(`Ollama request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let tokenCount = 0;
  let doneReason: string | undefined;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.trim()) continue;

        const chunk = tryParseNdjsonLine(line);
        if (!chunk) {
          // Skip a malformed/partial NDJSON line instead of aborting the
          // whole extraction over one bad chunk.
          continue;
        }

        full += chunk.message?.content ?? "";
        if (chunk.done_reason) doneReason = chunk.done_reason;
        tokenCount += 1;
        onProgress?.(Math.min(95, Math.round((tokenCount / MAX_PREDICT_TOKENS) * 100)));
      }
    }
  } catch (err) {
    throw new Error(
      `Extraction stream failed: ${err instanceof Error ? err.message : "unknown error"}`,
    );
  }

  onProgress?.(100);
  return {
    raw: full,
    parsed: parseJsonBlock(full),
    truncated: doneReason === "length",
  };
}
