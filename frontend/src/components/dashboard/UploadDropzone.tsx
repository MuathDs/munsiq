"use client";

import { UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

import { interpolate, type Messages } from "@/lib/messages";

import { MAX_FILES_PER_BATCH } from "./UploadProvider";

interface UploadDropzoneProps {
  onFilesSelected: (files: File[]) => void;
  t: Messages;
  /** Shown in the hint; the backend is the authority and enforces it. */
  maxMb: number;
}

/**
 * Where PDFs go in. The prototype's said "Plain-text (.txt) contracts" and
 * accepted only `.txt`, because it read text and sent it to a model. This one
 * takes what the backend takes: PDFs, which is what ZATCA invoices are.
 */
export function UploadDropzone({ onFilesSelected, t, maxMb }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    onFilesSelected(Array.from(list));
    // Clear it, or choosing the same file again fires no change event.
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        handleFiles(event.dataTransfer.files);
      }}
      className={`flex cursor-pointer flex-col items-center gap-[10px] rounded-2xl border-2 border-dashed px-8 py-12 text-center transition-colors ${
        isDragging ? "border-accent bg-accent/10" : "border-line-strong bg-surface hover:border-accent/60"
      }`}
    >
      <div className="flex h-[52px] w-[52px] items-center justify-center rounded-2xl bg-accent/14">
        <UploadCloud size={22} className="text-accent-strong" aria-hidden />
      </div>
      <p className="text-base font-semibold text-ink">{t.upload.drop}</p>
      <p className="text-[13px] text-ink-soft">
        {interpolate(t.upload.dropHint, { count: MAX_FILES_PER_BATCH, size: maxMb })}
      </p>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          inputRef.current?.click();
        }}
        className="mt-1 rounded-[9px] bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-strong"
      >
        {t.upload.browse}
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => handleFiles(event.target.files)}
      />
    </div>
  );
}
