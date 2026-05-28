/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { visualizer } from 'rollup-plugin-visualizer';

// Bundle audit (Phase 5). ``ANALYZE=1 npm run build`` writes
// ``dist/stats.html`` (treemap) and ``dist/stats.json`` (raw, machine-
// readable). Gated on the env var so normal + CI builds stay fast.
const analyze = process.env.ANALYZE === '1';

export default defineConfig({
  plugins: [
    react(),
    ...(analyze
      ? [
          visualizer({
            filename: 'dist/stats.html',
            template: 'treemap',
            gzipSize: true,
            brotliSize: false,
          }),
          visualizer({
            filename: 'dist/stats.json',
            template: 'raw-data',
            gzipSize: true,
            brotliSize: false,
          }),
        ]
      : []),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // Split slow-changing vendor code into its own cacheable chunks so the
    // app chunk shrinks + vendors don't re-download on every app update
    // (Phase 5 bundle trim). The editor + other routes are already lazy via
    // React.lazy, so they stay in their own route chunks automatically.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined;
          // Split the react-*dependent* libraries into their own cacheable
          // chunks. React core itself (+ its shims + misc deps) falls into
          // the catch-all ``vendor`` chunk, which keeps ``vendor`` a true
          // leaf: every edge points one-way INTO it, so there's no
          // vendor <-> vendor-react cycle. Asset loading is from local disk
          // in the Tauri shell, so a handful of extra chunks costs nothing.
          if (id.includes('react-router')) return 'vendor-router';
          if (id.includes('@tanstack')) return 'vendor-query';
          if (id.includes('@radix-ui')) return 'vendor-radix';
          if (id.includes('i18next')) return 'vendor-i18n';
          if (id.includes('lucide-react')) return 'vendor-icons';
          // @sentry/* intentionally stays in the catch-all ``vendor`` — a
          // dedicated ``vendor-sentry`` chunk creates a vendor↔vendor-sentry
          // cycle through transitive deps, and the Sentry SDK is only ~27 kB
          // gzipped (well under the Phase-5 spec's 50 kB lazy-load threshold).
          return 'vendor';
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: process.env.VITE_WS_PROXY_TARGET ?? 'ws://localhost:8000',
        ws: true,
      },
      '/health': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/storage': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/docs': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/redoc': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
