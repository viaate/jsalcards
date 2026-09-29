import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../src/App.svelte';
import { STATUS_KEYS, copy } from '../src/copy';

describe('App', () => {
  let app: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (app !== undefined) void unmount(app);
    app = undefined;
    document.body.innerHTML = '';
  });

  it('renders a full-viewport stage named for the app, with nothing on it but the key', () => {
    const target = document.createElement('div');
    document.body.append(target);

    app = mount(App, { target });
    flushSync();

    const main = target.querySelector('main');
    expect(main).not.toBeNull();
    expect(main?.querySelector('h1')?.textContent).toBe(copy.appName);
    // The legend names the four statuses in code order, each with its glyph, and claims none.
    const legend = main?.querySelector('ul.legend');
    expect(legend?.getAttribute('aria-label')).toBe(copy.legend.label);
    const keys = [...(legend?.querySelectorAll('li') ?? [])];
    expect(keys.map((key) => key.textContent.trim())).toEqual(
      STATUS_KEYS.map((key) => copy.status[key]),
    );
    for (const key of keys) {
      expect(key.querySelector('.glyph')?.getAttribute('aria-hidden')).toBe('true');
    }
    expect(main?.textContent.replace(legend?.textContent ?? '', '').trim()).toBe(copy.appName);
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

  it('asks the phone where it is once per press, and says so while it waits', () => {
    const asks: { done: (position: GeolocationPosition) => void; fail: () => void }[] = [];
    const geolocation = {
      getCurrentPosition: (done: (position: GeolocationPosition) => void, fail: () => void) => {
        asks.push({ done, fail });
      },
    };
    Object.defineProperty(navigator, 'geolocation', { value: geolocation, configurable: true });
    try {
      const target = document.createElement('div');
      document.body.append(target);
      app = mount(App, { target });
      flushSync();

      const button = target.querySelector<HTMLButtonElement>('button.locate');
      if (button === null) throw new Error('no locate button');
      expect(button.getAttribute('aria-label')).toBe(copy.map.locate);
      expect(button.textContent.trim()).toBe('');
      expect(button.getAttribute('aria-busy')).toBe('false');

      button.click();
      flushSync();
      expect(asks).toHaveLength(1);
      expect(button.getAttribute('aria-busy')).toBe('true');
      expect(button.classList.contains('is-locating')).toBe(true);
      // A second press while it waits asks nothing more.
      button.click();
      flushSync();
      expect(asks).toHaveLength(1);

      // No answer, or a place far from the US: it goes back to rest, and can be asked again.
      asks[0]?.fail();
      flushSync();
      expect(button.getAttribute('aria-busy')).toBe('false');
      button.click();
      flushSync();
      asks[1]?.done({ coords: { latitude: 51.5, longitude: -0.12 } } as GeolocationPosition);
      flushSync();
      expect(asks).toHaveLength(2);
      expect(button.classList.contains('is-locating')).toBe(false);
    } finally {
      Reflect.deleteProperty(navigator, 'geolocation');
    }
  });

  it(
    'opens the menu from its button beside the field, and Escape or a press elsewhere closes it',
    {
      timeout: 30_000,
    },
    async () => {
      const target = document.createElement('div');
      document.body.append(target);
      app = mount(App, { target });
      flushSync();

      const stage = target.querySelector<HTMLElement>('main.stage');
      const button = target.querySelector<HTMLButtonElement>('header.bar button.menu-button');
      if (button === null || stage === null) throw new Error('no menu button');
      expect(button.getAttribute('aria-label')).toBe(copy.menu.label);
      expect(button.getAttribute('aria-expanded')).toBe('false');
      expect(button.hasAttribute('aria-controls')).toBe(false);
      expect(button.textContent.trim()).toBe('');
      // Just after the search field in the top strip.
      expect(button.previousElementSibling?.classList.contains('search')).toBe(true);
      /** Waits until the page says so, as the menu's code and the app's services come in. */
      const until = async (check: () => boolean): Promise<void> => {
        await vi.waitFor(
          () => {
            flushSync();
            if (!check()) throw new Error('not yet');
          },
          { timeout: 20_000, interval: 20 },
        );
      };
      const panel = (): HTMLElement | null => target.querySelector<HTMLElement>('aside.menu');

      // Pressed, it opens the menu, which takes focus once it shows: what the map shows, and About.
      button.focus();
      button.click();
      await until(() => panel() !== null);
      const menu = panel();
      if (menu === null) throw new Error('no menu');
      expect(button.getAttribute('aria-expanded')).toBe('true');
      expect(button.getAttribute('aria-controls')).toBe(menu.id);
      expect(document.activeElement).toBe(menu);
      expect([...menu.querySelectorAll('h2')].map((heading) => heading.textContent)).toEqual([
        copy.menu.today,
        copy.menu.kinds,
      ]);
      expect(menu.querySelector('.item.is-on .name')?.textContent).toBe(copy.menu.all);

      // One status shown: the stage says which, for the key to step back from the others, and
      // that the map shows less than everything, for the dot on the button; all four again, and
      // it is as it was.
      expect(stage.hasAttribute('data-status')).toBe(false);
      expect(stage.hasAttribute('data-filtered')).toBe(false);
      menu.querySelectorAll<HTMLInputElement>('input[type="radio"]')[1]?.click();
      flushSync();
      expect(menu.querySelector('.item.is-on .name')?.textContent).toBe(copy.status.closed);
      expect(stage.dataset.status).toBe('0');
      expect(stage.hasAttribute('data-filtered')).toBe(true);
      menu.querySelectorAll<HTMLInputElement>('input[type="radio"]')[0]?.click();
      flushSync();
      expect(stage.hasAttribute('data-status')).toBe(false);
      expect(stage.hasAttribute('data-filtered')).toBe(false);
      // A kind of school hidden is a filter too.
      menu.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1]?.click();
      flushSync();
      expect(stage.hasAttribute('data-filtered')).toBe(true);
      expect(stage.hasAttribute('data-status')).toBe(false);
      menu.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1]?.click();
      flushSync();
      expect(stage.hasAttribute('data-filtered')).toBe(false);

      // Escape closes it, and the keyboard goes back to the button.
      const escape = new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
      });
      menu.dispatchEvent(escape);
      flushSync();
      expect(escape.defaultPrevented).toBe(true);
      expect(panel()).toBeNull();
      expect(button.getAttribute('aria-expanded')).toBe('false');
      expect(button.hasAttribute('aria-controls')).toBe(false);
      expect(document.activeElement).toBe(button);

      // Open again, a press on the map closes it and moves no focus.
      button.click();
      await until(() => panel() !== null);
      target
        .querySelector('.map')
        ?.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      flushSync();
      expect(panel()).toBeNull();

      // The button toggles it, and going to search closes it.
      button.click();
      await until(() => panel() !== null);
      button.click();
      await until(() => panel() === null);
      button.click();
      await until(() => panel() !== null);
      target.querySelector<HTMLInputElement>('input.search-input')?.focus();
      flushSync();
      expect(panel()).toBeNull();
      expect(button.getAttribute('aria-expanded')).toBe('false');

      // Back or Forward (a school opening or closing) closes it too.
      button.click();
      await until(() => panel() !== null);
      window.dispatchEvent(new PopStateEvent('popstate'));
      flushSync();
      expect(panel()).toBeNull();
    },
  );

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
