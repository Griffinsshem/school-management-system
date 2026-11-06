import type { Metadata } from "next";
// The typeface is served from this site (no requests to Google Fonts).
import "@fontsource-variable/atkinson-hyperlegible-next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "School Management System",
    template: "%s | School Management System",
  },
  description: "Run your school's records, people and day-to-day work in one place.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
