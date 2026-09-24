import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './styles/global.css';

import { mount } from 'svelte';

import App from './App.svelte';

const target = document.getElementById('app');
if (target === null) {
  throw new Error('Snowlight: missing #app mount point in index.html');
}

mount(App, { target });
