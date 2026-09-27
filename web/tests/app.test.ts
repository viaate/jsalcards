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

  it('goes to the search field on "/" from anywhere but a text field', () => {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(App, { target, props: { initialQuery: 'Duluth' } });
    flushSync();

    const input = target.querySelector<HTMLInputElement>('input.search-input');
    if (input === null) throw new Error('no search field');
    expect(input.getAttribute('aria-keyshortcuts')).toBe('/');
    const slash = (from: Element, init: KeyboardEventInit = {}): KeyboardEvent => {
      const event = new KeyboardEvent('keydown', {
        key: '/',
        bubbles: true,
        cancelable: true,
        ...init,
      });
      from.dispatchEvent(event);
      return event;
    };

    // From the page: the field takes focus with its text selected, and no "/" is typed.
    expect(slash(document.body).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);
    expect([input.selectionStart, input.selectionEnd]).toEqual([0, 'Duluth'.length]);

    // In a text field the key is the field's own; with a modifier it is the browser's.
    expect(slash(input).defaultPrevented).toBe(false);
    const other = document.createElement('textarea');
    document.body.append(other);
    other.focus();
    expect(slash(other).defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(other);
    expect(slash(document.body, { ctrlKey: true }).defaultPrevented).toBe(false);
    expect(slash(document.body, { metaKey: true }).defaultPrevented).toBe(false);
    expect(slash(document.body, { isComposing: true }).defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(other);
  });

  it('shows no update time until a live file is shown', () => {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(App, { target });
    flushSync();

    expect(target.querySelector('.updated')).toBeNull();
    expect(target.querySelector('time')).toBeNull();
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
