import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NexSafe AI — Predict. Protect. Prevent.",
  description: "Real-time road safety monitoring, grounded in your cameras and validated AI models.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
