import type { NextConfig } from "next";
import path from "node:path";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  outputFileTracingRoot: path.join(__dirname, "../.."),
  transpilePackages: ["@ai-video-studio/workflow-schema"],
  turbopack: isDev
    ? {
        rules: {
          "**/*.{tsx,jsx}": {
            loaders: [
              {
                loader: "@locator/webpack-loader",
                options: { env: "development" },
              },
            ],
          },
        },
      }
    : undefined,
};

export default nextConfig;
