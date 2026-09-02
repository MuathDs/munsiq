"use client";

import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";

interface UploadDropzoneProps {
  onFilesSelected: (files: File[]) => void;
}

export function UploadDropzone({ onFilesSelected }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    onFilesSelected(Array.from(fileList));
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
      className={`cursor-pointer rounded-2xl border-2 border-dashed px-8 py-12 flex flex-col items-center gap-[10px] text-center transition-colors ${
        isDragging ? "border-accent bg-accent/10" : "border-line-strong bg-surface"
      }`}
    >
      <div className="w-[52px] h-[52px] rounded-2xl bg-accent/14 flex items-center justify-center">
        <UploadCloud size={22} className="text-accent-strong" />
      </div>
      <p className="text-base font-semibold text-ink">Drag &amp; drop invoices here</p>
      <p className="text-[13px] text-ink-soft">
        Plain-text (.txt) contracts — batch upload up to 20 files at once
      </p>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          inputRef.current?.click();
        }}
        className="mt-1 rounded-[9px] bg-accent px-4 py-2 text-[13px] font-semibold text-white"
      >
        Browse files
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".txt"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  );
}
