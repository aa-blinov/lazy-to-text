// The screens, in sidebar order. A screen is a Svelte component that takes
// no props; it reads shared state from lib/backend.js and calls the runtime
// through lib/rpc.js.
import Transcribe from './Transcribe.svelte';
import Models from './Models.svelte';
import History from './History.svelte';
import PostProcessing from './PostProcessing.svelte';
import Settings from './Settings.svelte';
import Logs from './Logs.svelte';

export const views = [
  { id: 'transcribe', label: 'Transcribe', component: Transcribe },
  { id: 'models', label: 'Models', component: Models },
  { id: 'history', label: 'History', component: History },
  { id: 'postprocessing', label: 'Post-processing', component: PostProcessing },
  { id: 'settings', label: 'Settings', component: Settings },
  { id: 'logs', label: 'Logs', component: Logs },
];
