import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Single source of truth for dev proxy. Change via env on another machine if backend port/host differs.
const apiProxyTarget = process.env.VITE_DEV_API_PROXY || "http://127.0.0.1:8000";
export default defineConfig({
    plugins: [react()],
    server: {
        host: "0.0.0.0",
        port: 5173,
        proxy: {
            "/api": {
                target: apiProxyTarget,
                changeOrigin: false,   // сохраняем исходный Host от браузера (localhost:5173)
            },
            "/admin": {
                target: apiProxyTarget,
                changeOrigin: false,
            },
        },
    },
});
