import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import App from '../src/App.svelte';
import { copy } from '../src/copy';

describe('App', () => {
  let app: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (app !== undefined) void unmount(app);
    app = undefined;
    document.body.innerHTML = '';
  });

  it('renders an empty full-viewport stage named for the app', () => {
    const target = document.createElement('div');
    document.body.append(target);

    app = mount(App, { target });
    flushSync();

    const main = target.querySelector('main');
    expect(main).not.toBeNull();
    expect(main?.querySelector('h1')?.textContent).toBe(copy.appName);
    expect(main?.textContent.trim()).toBe(copy.appName);
  });
});
