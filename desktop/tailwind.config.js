import ui from '@monos/ui/tailwind-preset';

export default {
  presets: [ui],
  content: [
    './renderer/**/*.{html,svelte,js}',
    './node_modules/@monos/ui/src/**/*.svelte',
  ],
};
