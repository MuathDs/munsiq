import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The floating dev-route bubble sits over the document pane and would land in
  // every screenshot of the workspace. Compile and runtime errors still surface.
  devIndicators: false,
};

export default nextConfig;
