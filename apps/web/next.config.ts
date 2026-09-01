import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  outputFileTracingRoot: path.join(__dirname, "../.."),
  transpilePackages: ["@libtv/workflow-schema"],
};

export default nextConfig;
