import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import ReplayBar from '../ReplayBar.svelte';
import { reactiveProps } from './reactive-props.svelte';

describe('ReplayBar drawn anew (a theme in another face)', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(): { target: HTMLElement; props: { drawn: number } } {
    const target = document.createElement('div');
    document.body.append(target);
    const props = reactiveProps({ day: '2026-01-12', onexit: () => undefined, drawn: 0 });
    component = mount(ReplayBar, { target, props });
    flushSync();
    return { target, props };
  }

  it('draws a new bar, and the way back keeps the keyboard where it had it', () => {
    const { target, props } = show();
    const old = target.querySelector('.replay');
    const exit = target.querySelector<HTMLButtonElement>('.exit');
    exit?.focus();
    expect(document.activeElement).toBe(exit);
    props.drawn = 1;
    flushSync();
    const drawn = target.querySelector('.replay');
    expect(drawn).not.toBe(old);
    expect(target.querySelectorAll('.replay')).toHaveLength(1);
    const again = target.querySelector<HTMLButtonElement>('.exit');
    expect(again).not.toBe(exit);
    expect(document.activeElement).toBe(again);
  });

  it('takes no keyboard the way back did not have', () => {
    const { target, props } = show();
    const elsewhere = document.createElement('input');
    document.body.append(elsewhere);
    elsewhere.focus();
    props.drawn = 1;
    flushSync();
    expect(target.querySelector('.replay')).not.toBeNull();
    expect(document.activeElement).toBe(elsewhere);
    elsewhere.blur();
    props.drawn = 2;
    flushSync();
    expect(document.activeElement).toBe(document.body);
  });
});
