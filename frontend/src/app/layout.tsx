import type { Metadata } from "next";
import { IBM_Plex_Sans_Arabic, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

/**
 * IBM Plex Sans Arabic, declared here because font variables must sit on an
 * ancestor of everything that uses them and the root layout owns `<html>`.
 *
 * Without a real Arabic face the browser synthesises glyphs from a Latin font,
 * which breaks the cursive joins and looks wrong to anyone who reads Arabic.
 * `globals.css` applies it under `[dir="rtl"]`.
 */
const plexArabic = IBM_Plex_Sans_Arabic({
  variable: "--font-plex-arabic",
  subsets: ["arabic", "latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Munsiq",
  description: "AI-powered invoice and contract data extraction",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} ${plexArabic.variable} h-full antialiased`}
    >
      {/* The legacy dashboard at `/` relies on this column layout; the locale
          shell under /[locale] overrides `lang` and `dir` on its own wrapper. */}
      <body className="min-h-full flex flex-col bg-bg text-ink">{children}</body>
    </html>
  );
}
