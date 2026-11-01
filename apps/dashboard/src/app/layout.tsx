import type { Metadata } from "next";

import { Providers } from "@/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "LocalDeploy — Self-Hosted Deployment Platform",
  description:
    "Transform your computer or server into a self-hosted cloud hosting platform: Git deploys, Docker, domains, SSL, monitoring.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
