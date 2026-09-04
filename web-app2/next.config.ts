import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      // The ingest screen used to live at /sources.
      { source: "/sources", destination: "/ingest", permanent: true },
      { source: "/", destination: "/landing", permanent: false },
    ];
  },
};

export default nextConfig;
