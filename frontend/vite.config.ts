import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, "..");

function repoEnv(mode: string): Record<string, string> {
  return { ...loadEnv(mode, repoRoot, ""), ...loadEnv(mode, frontendDir, "") };
}

export default defineConfig(({ mode }) => {
  const env = repoEnv(mode);
  const apiHost = env.API_HOST || "127.0.0.1";
  const apiPort = env.API_PORT || "8000";
  const apiProxy = env.VITE_API_PROXY || `http://${apiHost}:${apiPort}`;
  const webPort = Number(env.WEB_PORT || env.VITE_DEV_PORT || 5173);
  const webHost = env.WEB_HOST === "true" || !env.WEB_HOST ? true : env.WEB_HOST;
  const prefillOn = mode === "development" && env.DEV_PREFILL_LOGIN !== "false";
  const prefillEmail = env.BOOTSTRAP_ADMIN_EMAIL || "";
  const prefillPassword = env.BOOTSTRAP_ADMIN_PASSWORD || "";

  return {
    envDir: repoRoot,
    plugins: [react()],
    define: {
      __DEV_LOGIN__: JSON.stringify(
        prefillOn && prefillEmail && prefillPassword
          ? { email: prefillEmail, password: prefillPassword }
          : { email: "", password: "" },
      ),
    },
    server: {
      host: webHost,
      port: webPort,
      strictPort: true,
      proxy: {
        "/api": apiProxy,
        "/uploads": apiProxy,
      },
    },
  };
});
