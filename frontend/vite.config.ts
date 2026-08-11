import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxy = env.VITE_API_PROXY || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      // Bind IPv4+IPv6 so both localhost and 127.0.0.1 work on Windows
      host: true,
      port: 5173,
      strictPort: true,
      proxy: {
        // Prefer 127.0.0.1 so proxy does not depend on IPv6 localhost resolution
        "/api": apiProxy,
        "/uploads": apiProxy,
      },
    },
  };
});
