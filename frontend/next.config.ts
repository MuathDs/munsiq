import type { NextConfig } from "next";

// Hostnames other than localhost that may load the dev server, e.g. a phone or a
// second machine on the LAN. Comma-separated in MUNSIQ_DEV_ORIGINS; a pasted
// "http://192.168.1.20:3000" is reduced to its hostname, which is what Next
// matches on. Development only: `next build` and `next start` ignore it.
const devOrigins = (process.env.MUNSIQ_DEV_ORIGINS ?? "")
  .split(",")
  .map((entry) =>
    entry
      .trim()
      .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
      .replace(/(:\d+)?(\/.*)?$/, ""),
  )
  .filter(Boolean);

const nextConfig: NextConfig = {
  allowedDevOrigins: devOrigins,

  // The floating dev-route bubble sits over the document pane and would land in
  // every screenshot of the workspace. Compile and runtime errors still surface.
  devIndicators: false,
};

export default nextConfig;
