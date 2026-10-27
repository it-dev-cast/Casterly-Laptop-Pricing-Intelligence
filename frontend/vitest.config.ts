import { defineConfig } from "vitest/config";
export default defineConfig({ test: { environment: "jsdom", include: ["src/**/*.test.tsx"],
  restoreMocks: true, clearMocks: true, fileParallelism: false } });
