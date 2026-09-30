import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow your workstation's local hostname and mDNS address in development
  allowedDevOrigins: [
    "desktop-jl94ltn.local",
    "desktop-jl94ltn",
    "*.local",
  ],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://127.0.0.1:8000/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;