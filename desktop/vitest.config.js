import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: { conditions: ['browser'], dedupe: ['svelte'] },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.js'],
    server: { deps: { inline: ['svelte', '@testing-library/svelte', '@testing-library/svelte-core'] } },
    globals: true,
  },
});
