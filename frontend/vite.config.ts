import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  // No React plugin: esbuild compiles JSX (tsconfig "react-jsx") and the aliases below send it to Preact.
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  resolve: {
    // Preact's compat layer is a drop in for what this app uses (hooks, lazy, Suspense,
    // useSyncExternalStore, createRoot) and saves about 60 KB gz on the first route.
    alias: [
      { find: /^react-dom\/client$/, replacement: "preact/compat/client" },
      { find: /^react-dom$/, replacement: "preact/compat" },
      { find: /^react\/jsx-runtime$/, replacement: "preact/jsx-runtime" },
      { find: /^react\/jsx-dev-runtime$/, replacement: "preact/jsx-dev-runtime" },
      { find: /^react$/, replacement: "preact/compat" },
    ],
  },
  build: {
    target: "es2019",
    modulePreload: { polyfill: true },
    assetsInlineLimit: 0,
    sourcemap: false,
    reportCompressedSize: true,
  },
  server: {
    port: 5173,
    // Optional: point VITE_API_URL at "" (empty) to use this proxy against a local Django.
    proxy: { "/api": "http://localhost:8000" },
  },
  preview: { port: 4173 },
});
