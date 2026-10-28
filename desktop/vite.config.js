import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

// Three pages, one build: the main window, the recording capsule and the
// result popup. The capsule and the popup are separate windows with their
// own tiny entry so they start fast and carry none of the main window's code.
// The pages carry a strict Content-Security-Policy. The dev server needs one
// more thing in it, a WebSocket for hot reload, and only the dev server gets
// it: it is added while serving and is not in the files that are built.
const devPolicy = {
  name: 'l2t-dev-csp',
  apply: 'serve',
  transformIndexHtml: (html) => html.replace('connect-src http://127.0.0.1:*', 'connect-src http://127.0.0.1:* ws://127.0.0.1:*'),
};

export default defineConfig({
  root: 'renderer',
  base: './',
  resolve: { dedupe: ['svelte'] },
  plugins: [svelte(), devPolicy],
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
  build: {
    outDir: '../dist-renderer',
    emptyOutDir: true,
    // Nothing is inlined as a data: URI. The policy allows fonts from 'self'
    // only, and Vite would otherwise fold the smallest font file into the CSS.
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, 'renderer/index.html'),
        overlay: resolve(import.meta.dirname, 'renderer/overlay.html'),
        popup: resolve(import.meta.dirname, 'renderer/popup.html'),
      },
    },
  },
});
