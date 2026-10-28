import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Listen on all network interfaces so the iPad can reach the dev server over Wi-Fi.
    host: true,
    port: 5173,
    strictPort: true,
    // The API server only listens locally; the iPad reaches it through here.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    rollupOptions: {
      input: { main: resolve(__dirname, "index.html"), admin: resolve(__dirname, "admin.html") },
    },
  },
});
