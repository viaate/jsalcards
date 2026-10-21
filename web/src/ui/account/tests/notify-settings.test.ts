// Settings > Notifications (NotifySettings.svelte): the button that asks for permission, the
// iPhone guide, the blocked and unsupported notes, and the per-type choices saved as changed.
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  NotifyClient,
  NotifySettings as Settings,
  NotifyState,
  Support,
} from '../../../account/notify';
import type { AccountStore } from '../../../account/session';
import NotifySettings from '../NotifySettings.svelte';

const DEFAULTS: Settings = {
  status: true,
  chance: true,
  threshold: 50,
  night_before: false,
  night_time: '20:00',
  quiet_from: '22:00',
  quiet_to: '05:00',
};

function fakeClient(over: Partial<NotifyClient> = {}, devices = 0, on = false) {
  let state: NotifyState = { settings: DEFAULTS, devices };
  const saves: Partial<Settings>[] = [];
  const turnOn = vi.fn<NotifyClient['turnOn']>(() => Promise.resolve('on'));
  const client: NotifyClient = {
    permission: () => 'default',
    isOn: () => Promise.resolve(on),
    turnOn,
    turnOff: () => Promise.resolve(),
    turnOffAll: () => Promise.resolve(0),
    follow: () => Promise.resolve(),
    read: () => Promise.resolve(state),
    save: (change) => {
      saves.push(change);
      state = { ...state, settings: { ...state.settings, ...change } };
      return Promise.resolve(state);
    },
    ...over,
  };
  return { client, saves, turnOn };
}

let component: ReturnType<typeof mount> | undefined;
afterEach(() => {
  if (component !== undefined) void unmount(component);
  component = undefined;
  document.body.innerHTML = '';
});

async function show(client: NotifyClient, support: Support, schools = 1): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  component = mount(NotifySettings, {
    target,
    props: { store: {} as AccountStore, schools, client, support },
  });
  flushSync();
  await settle();
  return target;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

/** The `index`-th of `items`; fails the test when there is none. */
function at<T>(items: ArrayLike<T>, index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`no item ${String(index)}`);
  return item;
}

const buttons = (target: HTMLElement): string[] =>
  [...target.querySelectorAll('button')].map((b) => b.textContent.trim());

describe('Settings > Notifications', () => {
  it('asks for nothing until the button is pressed', async () => {
    const { client, turnOn } = fakeClient();
    const target = await show(client, 'supported');
    expect(turnOn).not.toHaveBeenCalled();
    expect(buttons(target)).toEqual(['Turn on notifications']);
    // No browser gets them yet: no choices to make.
    expect(target.querySelector('fieldset')).toBeNull();
    target.querySelector('button')?.click();
    await settle();
    expect(turnOn).toHaveBeenCalledTimes(1);
    expect(target.textContent).toContain('Notifications are on for this device.');
    expect(buttons(target)).toEqual(['Turn off on this device']);
    expect(target.querySelector('fieldset')).not.toBeNull();
  });

  it('turns notifications off on every device of the account', async () => {
    const turnOffAll = vi.fn<NotifyClient['turnOffAll']>(() => Promise.resolve(0));
    const { client } = fakeClient({ turnOffAll }, 3, true);
    const target = await show(client, 'supported');
    expect(target.textContent).toContain('On 3 devices');
    expect(buttons(target)).toEqual(['Turn off on this device', 'Turn off on all devices']);
    at(target.querySelectorAll('button'), 1).click();
    await settle();
    expect(turnOffAll).toHaveBeenCalledTimes(1);
    expect(buttons(target)).toEqual(['Turn on notifications']);
    expect(target.textContent).not.toContain('On 3 devices');
  });

  it('shows the iPhone guide instead of a button that cannot work', async () => {
    const { client } = fakeClient();
    const target = await show(client, 'ios-install');
    const guide = target.querySelector('[data-testid="ios-guide"]');
    expect(guide?.textContent).toContain('On iPhone, add Snowlight to your home screen first');
    expect(guide?.querySelectorAll('li').length).toBe(3);
    expect(buttons(target)).toEqual([]);
  });

  it('says when the browser cannot, and when it blocks them', async () => {
    const unsupported = await show(fakeClient().client, 'unsupported');
    expect(unsupported.textContent).toContain(
      'This browser does not show notifications from websites.',
    );
    if (component !== undefined) void unmount(component);
    document.body.innerHTML = '';
    const blocked = fakeClient({ turnOn: vi.fn(() => Promise.resolve('blocked' as const)) });
    const target = await show(blocked.client, 'supported');
    target.querySelector('button')?.click();
    await settle();
    expect(target.textContent).toContain('Notifications are blocked for this site.');
  });

  it('saves each choice as it changes: types, threshold 30/50/70, evening time, quiet hours', async () => {
    const { client, saves } = fakeClient({}, 1, true);
    const target = await show(client, 'supported');
    const boxes = [...target.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(boxes.map((b) => b.checked)).toEqual([true, true, false, true]);
    const threshold = at(target.querySelectorAll<HTMLSelectElement>('select'), 0);
    expect([...threshold.options].map((o) => o.textContent)).toEqual(['30%', '50%', '70%']);
    expect(threshold.value).toBe('50');
    threshold.value = '70';
    threshold.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    at(boxes, 0).click();
    await settle();
    at(boxes, 2).click();
    await settle();
    const night = at(target.querySelectorAll<HTMLSelectElement>('select'), 1);
    expect(night.value).toBe('20:00');
    expect(
      at(
        [...night.options].map((o) => o.textContent),
        0,
      ),
    ).toBe('5:00 PM');
    night.value = '19:30';
    night.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    at(boxes, 3).click();
    await settle();
    expect(saves).toEqual([
      { threshold: 70 },
      { status: false },
      { night_before: true },
      { night_time: '19:30' },
      { quiet_from: '00:00', quiet_to: '00:00' },
    ]);
    expect(target.querySelector('[role="status"]')?.textContent.trim()).toBe('Saved');
  });

  it('says so when there is no saved school', async () => {
    const target = await show(fakeClient().client, 'supported', 0);
    expect(target.textContent).toContain('Save a school to get notifications about it.');
  });
});
