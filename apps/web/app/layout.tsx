import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@xyflow/react/dist/style.css";
import "./globals.css";
import { TooltipProvider } from "@/components/ui/tooltip";

export const metadata: Metadata = {
  title: "AI Video Studio",
  description: "Project-based AI video creation workspace",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN" className="dark font-sans" suppressHydrationWarning>
      <body><TooltipProvider>{children}</TooltipProvider></body>
    </html>
  );
}
