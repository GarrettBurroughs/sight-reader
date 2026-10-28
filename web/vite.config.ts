import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Listen on all network interfaces so the iPad can reach the dev server over Wi-Fi.
    host: true,
    port: 5173,
    strictPort: true,
    // The API server only listens locally; the iPad reaches it through here. Keep the Host header
    // so the API sees the address the browser used (the iPad app download is preset to it).
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: {
    rollupOptions: {
      input: { main: resolve(__dirname, "index.html"), admin: resolve(__dirname, "admin.html") },
    },
  },
});
