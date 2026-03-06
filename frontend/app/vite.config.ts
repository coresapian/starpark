import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.LINKSPOT_API_TARGET || "http://127.0.0.1:8000";
  const apiProxy = {
    "/api": {
      target: apiTarget,
      changeOrigin: true,
      secure: false
    }
  };

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 4173,
      proxy: apiProxy
    },
    preview: {
      host: "0.0.0.0",
      port: 4174,
      proxy: apiProxy
    },
    build: {
      outDir: "dist",
      emptyOutDir: true
    }
  };
});
