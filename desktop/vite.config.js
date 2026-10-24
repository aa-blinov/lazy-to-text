import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

// Three pages, one build: the main window, the recording capsule and the
// result popup. The capsule and the popup are separate windows with their
// own tiny entry so they start fast and carry none of the main window's code.
export default defineConfig({
  root: 'renderer',
  base: './',
  plugins: [svelte()],
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
  build: {
    outDir: '../dist-renderer',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, 'renderer/index.html'),
        overlay: resolve(import.meta.dirname, 'renderer/overlay.html'),
        popup: resolve(import.meta.dirname, 'renderer/popup.html'),
      },
    },
  },
});
