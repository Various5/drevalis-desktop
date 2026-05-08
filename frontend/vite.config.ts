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
