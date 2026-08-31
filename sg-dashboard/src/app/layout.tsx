import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "react-hot-toast";

export const metadata: Metadata = {
  title: "SG Trading Platform",
  description: "NSE/BSE algorithmic trading dashboard",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-background text-text-primary antialiased font-sans">
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#1A2235",
              color: "#F1F5F9",
              border: "1px solid #1E2D45",
              borderRadius: "6px",
              fontSize: "13px",
            },
            success: { iconTheme: { primary: "#10B981", secondary: "#0A0E1A" } },
            error: { iconTheme: { primary: "#EF4444", secondary: "#0A0E1A" } },
          }}
        />
      </body>
    </html>
  );
}
