/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react()],
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
