import './app.css';
import { mount } from 'svelte';
import Overlay from './Overlay.svelte';

export default mount(Overlay, { target: document.getElementById('app') });
