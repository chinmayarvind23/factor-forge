import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./styles.css";

export const metadata: Metadata = {
  title: "FactorForge · Research console",
  description:
    "A local research workspace that turns an investment idea into a reviewable brief.",
};

/** Keep document metadata server-side while the console owns browser interactions. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
