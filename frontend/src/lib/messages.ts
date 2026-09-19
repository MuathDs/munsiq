/**
 * The message catalogue.
 *
 * `Messages` is derived from the English dictionary, so Arabic must supply
 * exactly the same keys or TypeScript fails the build. A half-translated UI is
 * a compile error rather than something a reviewer discovers mid-document.
 *
 * The Arabic here is written, not machine-translated. Terms follow ZATCA's own
 * vocabulary — "الرقم الضريبي" for the VAT registration number, "موثّق" for a
 * value carried by the signed XML attachment.
 */

import type { Locale } from "./i18n";

const en = {
  appName: "Munsiq",
  workspace: {
    title: "Validation workspace",
    document: "Document",
    fields: "Fields",
    page: "Page",
    of: "of",
    noPages: "This document has no rendered pages.",
    loading: "Loading…",
    untitled: "Untitled document",
    fit: "Fit page to pane",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    resize: "Resize panes",
  },
  status: {
    to_review: "To review",
    reviewing: "Reviewing",
    confirmed: "Confirmed",
    approved: "Approved",
    exported: "Exported",
    rejected: "Rejected",
    failed: "Failed",
    processing: "Processing",
    importing: "Importing",
    exporting: "Exporting",
  },
  provenance: {
    verified: "Verified (XML)",
    verifiedTooltip:
      "Read directly from the UBL attachment the supplier cryptographically signed and filed with ZATCA. Not a model reading — this value is authoritative.",
    extracted: "Extracted (AI)",
    extractedTooltip:
      "Read from the page by the extraction model. Advisory: check it against the highlighted region before confirming.",
    mismatch: "Mismatch",
    mismatchTooltip:
      "The signed XML and the model disagree. The XML value is authoritative. Resolve this before confirming.",
    human: "Corrected",
    humanTooltip: "A reviewer set this value.",
    ocrRule: "Not extracted",
    ocrRuleTooltip:
      "No value was extracted for this field. Nobody has verified whether it is absent from the document.",
    confidence: "Confidence",
    signedXml: "Signed XML",
    modelRead: "Model read",
    unlock: "Edit anyway",
    readOnlyHint: "Read-only: this value comes from the signed attachment.",
  },
  tiers: {
    blocking: "Blocking",
    blockingHint: "Must be resolved before this document can be confirmed.",
    review: "Needs review",
    reviewHint: "Check these against the document.",
    validated: "Auto-validated",
    validatedCount: "{count} fields auto-validated",
    show: "Show",
    hide: "Hide",
    collapsedSummary: "{count} auto-validated fields hidden",
  },
  blockers: {
    title: "Blocking findings",
    none: "No blocking findings.",
    countOne: "1 finding blocks confirmation",
    countMany: "{count} findings block confirmation",
    jumpHint: "Alt+B jumps to the next blocking field",
    openField: "Open field",
  },
  source: {
    signed: "Signed XML · no AI",
    model: "AI · {model}",
  },
  zatca: {
    title: "ZATCA compliance",
    short: "ZATCA",
    checks: "{passed}/{total}",
    subtitle: "Checks run against this document's data",
    notChecked: "Not checked",
    vatValid: "Category valid",
    vatInvalid: "Category not recognised",
    embeddedUbl: "Embedded UBL",
    embeddedUblYes: "Present",
    embeddedUblNo: "Absent",
    qr: "QR code",
    qrMatch: "Decoded and matching",
    qrMismatch: "Does not match",
    qrAbsent: "Not present",
    trn: "Seller VAT number",
    trnValid: "Checksum valid",
    trnInvalid: "Checksum failed",
    vatCategory: "VAT category",
    unknown: "Unknown",
    modelVersion: "Model",
    noModel: "No model was used — answered from signed XML",
  },
  actions: {
    confirm: "Confirm",
    confirming: "Confirming…",
    confirmed: "Confirmed",
    revert: "Revert",
    save: "Save",
    saving: "Saving…",
    saved: "Saved",
    saveFailed: "Could not save",
    retry: "Retry",
    shortcuts: "Keyboard shortcuts",
    close: "Close",
    language: "العربية",
    resolveFirst: "Resolve {count} blocking findings before confirming",
    confirmFailed: "Could not reach the server. Nothing was confirmed — try again.",
  },
  shortcuts: {
    title: "Keyboard shortcuts",
    nextField: "Next field",
    prevField: "Previous field",
    accept: "Accept and advance",
    revert: "Revert to the extracted value",
    confirm: "Confirm the document",
    nextBlocker: "Jump to the next blocking field",
    help: "Show this panel",
  },
  errors: {
    blockedTitle: "Cannot confirm yet",
    loadFailed: "Could not load this annotation.",
    notFound: "Annotation not found.",
  },
};

// No `as const`: the dictionary's SHAPE is the contract, not its wording.
// With literal types every Arabic string would have to equal its English
// counterpart, which is the opposite of the point.
export type Messages = typeof en;

const ar: Messages = {
  appName: "منصق",
  workspace: {
    title: "مساحة التحقق",
    document: "المستند",
    fields: "الحقول",
    page: "صفحة",
    of: "من",
    noPages: "لا توجد صفحات مُهيّأة لهذا المستند.",
    loading: "جارٍ التحميل…",
    untitled: "مستند بلا رقم",
    fit: "ملاءمة الصفحة للوحة",
    zoomIn: "تكبير",
    zoomOut: "تصغير",
    resize: "تغيير حجم اللوحتين",
  },
  status: {
    to_review: "بانتظار المراجعة",
    reviewing: "قيد المراجعة",
    confirmed: "مُعتمدة",
    approved: "مُصادق عليها",
    exported: "مُصدَّرة",
    rejected: "مرفوضة",
    failed: "فشلت",
    processing: "قيد المعالجة",
    importing: "قيد الاستيراد",
    exporting: "قيد التصدير",
  },
  provenance: {
    verified: "موثّق (XML)",
    verifiedTooltip:
      "مقروء مباشرةً من ملف UBL المرفق الذي وقّعه المورّد رقمياً وأرسله إلى هيئة الزكاة والضريبة والجمارك. ليست قراءة نموذج — هذه القيمة معتمدة.",
    extracted: "مستخرج (AI)",
    extractedTooltip:
      "استخرجه النموذج من صورة المستند. قيمة استرشادية: تحقّق منها في المنطقة المظللة قبل الاعتماد.",
    mismatch: "تعارض",
    mismatchTooltip:
      "ملف XML الموقّع والنموذج لا يتفقان. القيمة المعتمدة هي قيمة XML. يجب حلّ هذا التعارض قبل الاعتماد.",
    human: "مُصحّح",
    humanTooltip: "قام أحد المراجعين بتعيين هذه القيمة.",
    ocrRule: "غير مستخرج",
    ocrRuleTooltip:
      "لم تُستخرج أي قيمة لهذا الحقل، ولم يتحقق أحد بعد مما إذا كان غير موجود في المستند.",
    confidence: "درجة الثقة",
    signedXml: "ملف XML الموقّع",
    modelRead: "قراءة النموذج",
    unlock: "تعديل على أي حال",
    readOnlyHint: "للقراءة فقط: هذه القيمة مصدرها المرفق الموقّع.",
  },
  tiers: {
    blocking: "حاجب",
    blockingHint: "يجب حلّها قبل إمكانية اعتماد هذا المستند.",
    review: "بحاجة إلى مراجعة",
    reviewHint: "تحقّق من هذه القيم بمقارنتها بالمستند.",
    validated: "موثّقة تلقائياً",
    // Label-then-count, not "{count} حقول": Arabic number agreement changes the
    // noun with the count (حقلان، ٣ حقول، ١١ حقلاً), which a single template
    // cannot get right. The colon form is correct for every count.
    validatedCount: "حقول موثّقة تلقائياً: {count}",
    show: "إظهار",
    hide: "إخفاء",
    collapsedSummary: "حقول موثّقة تلقائياً مخفية: {count}",
  },
  blockers: {
    title: "الملاحظات الحاجبة",
    none: "لا توجد ملاحظات حاجبة.",
    countOne: "ملاحظة واحدة تمنع الاعتماد",
    countMany: "ملاحظات تمنع الاعتماد: {count}",
    jumpHint: "Alt+B للانتقال إلى الحقل الحاجب التالي",
    openField: "فتح الحقل",
  },
  source: {
    signed: "XML موقّع · بلا ذكاء اصطناعي",
    model: "ذكاء اصطناعي · {model}",
  },
  zatca: {
    title: "الامتثال لهيئة الزكاة والضريبة",
    short: "زاتكا",
    checks: "{passed}/{total}",
    subtitle: "فحوصات أُجريت على بيانات هذا المستند",
    notChecked: "لم يُفحص",
    vatValid: "الفئة صحيحة",
    vatInvalid: "الفئة غير معروفة",
    embeddedUbl: "ملف UBL المضمّن",
    embeddedUblYes: "موجود",
    embeddedUblNo: "غير موجود",
    qr: "رمز الاستجابة السريعة",
    qrMatch: "تم فكّه ومطابق",
    qrMismatch: "غير مطابق",
    qrAbsent: "غير موجود",
    trn: "الرقم الضريبي للبائع",
    trnValid: "الصيغة صحيحة",
    trnInvalid: "الصيغة غير صحيحة",
    vatCategory: "فئة الضريبة",
    unknown: "غير معروف",
    modelVersion: "النموذج",
    noModel: "لم يُستخدم أي نموذج — القيم من ملف XML الموقّع",
  },
  actions: {
    confirm: "اعتماد",
    confirming: "جارٍ الاعتماد…",
    confirmed: "تم الاعتماد",
    revert: "تراجع",
    save: "حفظ",
    saving: "جارٍ الحفظ…",
    saved: "تم الحفظ",
    saveFailed: "تعذّر الحفظ",
    retry: "إعادة المحاولة",
    shortcuts: "اختصارات لوحة المفاتيح",
    close: "إغلاق",
    language: "English",
    resolveFirst: "يلزم حلّ الملاحظات الحاجبة قبل الاعتماد: {count}",
    confirmFailed: "تعذّر الوصول إلى الخادم. لم يُعتمد شيء — حاول مجدداً.",
  },
  shortcuts: {
    title: "اختصارات لوحة المفاتيح",
    nextField: "الحقل التالي",
    prevField: "الحقل السابق",
    accept: "قبول والانتقال",
    revert: "الرجوع إلى القيمة المستخرجة",
    confirm: "اعتماد المستند",
    nextBlocker: "الانتقال إلى الحقل الحاجب التالي",
    help: "عرض هذه اللوحة",
  },
  errors: {
    blockedTitle: "لا يمكن الاعتماد بعد",
    loadFailed: "تعذّر تحميل هذه المراجعة.",
    notFound: "المراجعة غير موجودة.",
  },
};

const CATALOGUE: Record<Locale, Messages> = { ar, en };

export function messagesFor(locale: Locale): Messages {
  return CATALOGUE[locale];
}

/** Substitute `{name}` placeholders. Deliberately tiny — no ICU needed for two locales. */
export function interpolate(
  template: string,
  values: Record<string, string | number>,
): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}
