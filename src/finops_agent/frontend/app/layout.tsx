import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL || "https://main.d1e2bsg3elvnb4.amplifyapp.com"
  ),
  title: "FinOps Agent: Autonomous Cloud Economics on AWS",
  description:
    "Autonomous cloud economics agent built with AWS CDK, Bedrock AgentCore Gateway, and Next.js to optimize AWS commitment ROI.",
  openGraph: {
    title: "FinOps Agent: Autonomous Cloud Economics on AWS",
    description:
      "Autonomous cloud economics agent built with AWS CDK, Bedrock AgentCore Gateway, and Next.js to optimize AWS commitment ROI.",
    url: "https://main.d1e2bsg3elvnb4.amplifyapp.com",
    siteName: "FinOps Agent",
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "FinOps Agent: Autonomous Cloud Economics on AWS",
    description:
      "Autonomous cloud economics agent built with AWS CDK, Bedrock AgentCore Gateway, and Next.js to optimize AWS commitment ROI.",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
