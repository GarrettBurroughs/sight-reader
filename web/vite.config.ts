import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Listen on all network interfaces so the iPad can reach the dev server over Wi-Fi.
    host: true,
    port: 5173,
    strictPort: true,
  },
});
