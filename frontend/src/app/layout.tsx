import type { Metadata } from "next";
import Link from "next/link";
import {
  Activity,
  LayoutDashboard,
  Sliders,
  ListOrdered,
  Briefcase,
  BarChart2,
} from "lucide-react";
import "./globals.css";

export const metadata: Metadata = {
  title: "SignalDesk - Quantitative Terminal",
  description: "Stage-2 VCP & Mean Reversion Strategy Terminal",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className="bg-slate-950 text-slate-100 min-h-screen"
        suppressHydrationWarning
      >
        {/* Global Top Navbar */}
        <header className="border-b border-slate-800/80 bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div className="flex items-center gap-10">
              {/* Fancy / Larger SignalDesk Logo */}
              <Link
                href="/"
                className="group flex items-center gap-2.5 transition-transform hover:scale-[1.02]"
              >
                <div className="relative flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-500/20 to-teal-500/10 border border-emerald-500/30 group-hover:border-emerald-400/60 shadow-lg shadow-emerald-500/10 transition-all">
                  <Activity className="h-5 w-5 text-emerald-400 group-hover:text-emerald-300 transition-colors" />
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                    Signal
                    <span className="bg-gradient-to-r from-emerald-400 to-teal-300 bg-clip-text text-transparent">
                      Desk
                    </span>
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-1.5 py-0.2 bg-emerald-950/80 text-emerald-400 border border-emerald-800/80 rounded tracking-wider">
                    PRO
                  </span>
                </div>
              </Link>

              {/* Navigation Links */}
              <nav className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
                <Link
                  href="/"
                  className="px-3 py-2 rounded-md hover:text-white hover:bg-slate-800/80 transition flex items-center gap-2"
                >
                  <LayoutDashboard className="h-4 w-4 text-slate-400" />{" "}
                  Dashboard
                </Link>
                <Link
                  href="/scanner"
                  className="px-3 py-2 rounded-md hover:text-white hover:bg-slate-800/80 transition flex items-center gap-2"
                >
                  <Sliders className="h-4 w-4 text-slate-400" /> Scanner
                </Link>
                <Link
                  href="/results"
                  className="px-3 py-2 rounded-md hover:text-white hover:bg-slate-800/80 transition flex items-center gap-2"
                >
                  <ListOrdered className="h-4 w-4 text-slate-400" /> Signals &
                  Orders
                </Link>
                <Link
                  href="/holdings"
                  className="px-3 py-2 rounded-md hover:text-white hover:bg-slate-800/80 transition flex items-center gap-2"
                >
                  <Briefcase className="h-4 w-4 text-slate-400" /> Holdings
                </Link>
                <Link
                  href="/backtest"
                  className="px-3 py-2 rounded-md hover:text-white hover:bg-slate-800/80 transition flex items-center gap-2"
                >
                  <BarChart2 className="h-4 w-4 text-slate-400" /> Backtest
                </Link>
              </nav>
            </div>

            {/* KiteConnect Session Badge */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-emerald-950/40 border border-emerald-800/70 px-3 py-1.5 rounded-full text-xs text-emerald-400 font-medium shadow-sm">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                Kite Connected
              </div>
            </div>
          </div>
        </header>

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
