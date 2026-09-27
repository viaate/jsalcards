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

  it('marks the wordmark for masking, and every string comes from the copy', () => {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(App, { target, props: { initialQuery: 'Duluth' } });
    flushSync();

    expect(target.querySelector('h1.wordmark')?.hasAttribute('data-brand')).toBe(true);
    const input = target.querySelector('input.search-input');
    expect(input?.getAttribute('placeholder')).toBe(copy.search.placeholder);
    expect(input?.getAttribute('aria-label')).toBe(copy.search.placeholder);
    expect(target.querySelector('.search-clear')?.getAttribute('aria-label')).toBe(
      copy.search.clear,
    );
  });

  it('is a search field with nothing to list until results arrive', () => {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(App, { target });
    flushSync();

    const input = target.querySelector('input.search-input');
    expect(input?.getAttribute('role')).toBe('combobox');
    expect(input?.getAttribute('aria-expanded')).toBe('false');
    expect(input?.hasAttribute('aria-controls')).toBe(false);
    expect(target.querySelector('[role="listbox"]')).toBeNull();
    // Nothing is typed, so there is nothing to clear and nothing announced.
    expect(target.querySelector('.search-clear')).toBeNull();
    expect(target.querySelector('[role="status"]')?.textContent).toBe('');
  });

  it('handles Escape itself: with no list showing, it clears the text', () => {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(App, { target, props: { initialQuery: 'Duluth' } });
    flushSync();

    const input = target.querySelector<HTMLInputElement>('input.search-input');
    if (input === null) throw new Error('no search field');
    expect(input.value).toBe('Duluth');
    const escape = (isComposing = false): KeyboardEvent => {
      const event = new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
        isComposing,
      });
      input.dispatchEvent(event);
      flushSync();
      return event;
    };
    // Escape while an input method composes cancels the composition, nothing more.
    expect(escape(true).defaultPrevented).toBe(false);
    expect(input.value).toBe('Duluth');
    // The browser's own clear of a search field is held back: the app decides what Escape does.
    expect(escape().defaultPrevented).toBe(true);
    expect(input.value).toBe('');
    expect(target.querySelector('.search-clear')).toBeNull();
    // An empty field leaves Escape to the page.
    expect(escape().defaultPrevented).toBe(false);
  });
});
