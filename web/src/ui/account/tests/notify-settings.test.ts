// Settings > Notifications (NotifySettings.svelte): the header switch that asks for permission,
// the iPhone row and its steps, the blocked and unsupported values, and the per-type switches,
// threshold segments and times saved as they change.
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

/** Every switch, the header's (this device) first. */
const switches = (target: HTMLElement): HTMLInputElement[] => [
  ...target.querySelectorAll<HTMLInputElement>('input[role="switch"]'),
];

const device = (target: HTMLElement): HTMLInputElement | null =>
  target.querySelector<HTMLInputElement>('input[aria-label="Notifications on this device"]');

describe('Settings > Notifications', () => {
  it('asks for nothing until the header switch is flipped', async () => {
    const { client, turnOn } = fakeClient();
    const target = await show(client, 'supported');
    expect(turnOn).not.toHaveBeenCalled();
    expect(target.querySelector('h3')?.textContent).toBe('Notifications');
    expect(device(target)?.checked).toBe(false);
    // No browser gets them yet: the header switch is all there is.
    expect(switches(target)).toHaveLength(1);
    expect(buttons(target)).toEqual([]);
    device(target)?.click();
    await settle();
    expect(turnOn).toHaveBeenCalledTimes(1);
    expect(device(target)?.checked).toBe(true);
    expect(switches(target)).toHaveLength(5);
    // No sentence explains any of it.
    expect(target.querySelectorAll('p')).toHaveLength(0);
  });

  it('turns this device off from the same switch', async () => {
    const turnOff = vi.fn<NotifyClient['turnOff']>(() => Promise.resolve());
    const { client } = fakeClient({ turnOff }, 1, true);
    const target = await show(client, 'supported');
    expect(device(target)?.checked).toBe(true);
    device(target)?.click();
    await settle();
    expect(turnOff).toHaveBeenCalledTimes(1);
    expect(device(target)?.checked).toBe(false);
  });

  it('shows the switch as it was when turning on does not work', async () => {
    const { client } = fakeClient({ turnOn: vi.fn(() => Promise.resolve('failed' as const)) });
    const target = await show(client, 'supported');
    device(target)?.click();
    await settle();
    expect(device(target)?.checked).toBe(false);
    expect(target.querySelector('[role="status"]')?.textContent.trim()).toBe('Try again');
  });

  it('turns notifications off on every device of the account from one row in its own group', async () => {
    const turnOffAll = vi.fn<NotifyClient['turnOffAll']>(() => Promise.resolve(0));
    const { client } = fakeClient({ turnOffAll }, 3, true);
    const target = await show(client, 'supported');
    expect(buttons(target)).toHaveLength(1);
    const action = target.querySelector('button.action');
    expect(action?.textContent).toContain('3 devices');
    expect(action?.parentElement?.classList.contains('group')).toBe(true);
    expect(action?.parentElement?.querySelector('[role="switch"]')).toBeNull();
    at(target.querySelectorAll('button'), 0).click();
    await settle();
    expect(turnOffAll).toHaveBeenCalledTimes(1);
    expect(device(target)?.checked).toBe(false);
    expect(buttons(target)).toEqual([]);
    expect(target.textContent).not.toContain('3 devices');
  });

  it('gives iPhone Safari one row that opens the steps, How as its value, and no switch', async () => {
    const { client } = fakeClient();
    const target = await show(client, 'ios-install');
    const guide = target.querySelector('[data-testid="ios-guide"]');
    expect(guide?.textContent).toContain('Add to home screen first');
    expect(switches(target)).toHaveLength(0);
    expect(target.querySelectorAll('li')).toHaveLength(0);
    const how = at(target.querySelectorAll('button'), 0);
    expect(how).toBe(guide);
    expect(how.querySelector('.value')?.textContent).toBe('How');
    expect(how.getAttribute('aria-expanded')).toBe('false');
    how.click();
    await settle();
    expect(how.getAttribute('aria-expanded')).toBe('true');
    expect([...target.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
      'In Safari, tap Share, then Add to Home Screen',
      'Open Snowlight from your home screen',
      'Turn on notifications here',
    ]);
  });

  it('says when the browser cannot, and when it blocks them', async () => {
    const unsupported = await show(fakeClient().client, 'unsupported');
    expect(unsupported.textContent).toContain('Not in this browser');
    expect(switches(unsupported)).toHaveLength(0);
    if (component !== undefined) void unmount(component);
    document.body.innerHTML = '';
    const blocked = fakeClient({ turnOn: vi.fn(() => Promise.resolve('blocked' as const)) });
    const target = await show(blocked.client, 'supported');
    device(target)?.click();
    await settle();
    expect(target.textContent).toContain('Blocked in site settings');
    expect(device(target)).toBeNull();
  });

  it('saves each choice as it changes: types, threshold 30/50/70, evening time, quiet hours', async () => {
    const { client, saves } = fakeClient({}, 1, true);
    const target = await show(client, 'supported');
    expect(switches(target).map((b) => b.checked)).toEqual([true, true, true, false, true]);
    const segments = [...target.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
    expect(segments.map((r) => r.closest('label')?.textContent.trim())).toEqual([
      '30%',
      '50%',
      '70%',
    ]);
    expect(segments.map((r) => r.checked)).toEqual([false, true, false]);
    expect(target.querySelector('[role="radiogroup"]')?.getAttribute('aria-label')).toBe(
      'Alert when the chance reaches',
    );
    // Quiet hours: what they hold back as the label, the range as the value, not a sentence.
    const quiet = [...target.querySelectorAll<HTMLSelectElement>('select')];
    expect(quiet.map((s) => s.value)).toEqual(['22:00', '05:00']);
    const quietRow = at(quiet, 0).closest('.row');
    expect(quietRow?.querySelector('.label')?.textContent).toBe('Chance alerts only');
    expect(quietRow?.lastElementChild?.contains(at(quiet, 1))).toBe(true);
    at(segments, 2).click();
    await settle();
    expect(at(segments, 2).closest('label')?.classList.contains('on')).toBe(true);
    at(switches(target), 1).click();
    await settle();
    at(switches(target), 3).click();
    await settle();
    const night = at(target.querySelectorAll<HTMLSelectElement>('select'), 0);
    expect(night.value).toBe('20:00');
    expect(night.closest('label')?.textContent).toContain('Send at');
    expect(
      at(
        [...night.options].map((o) => o.textContent),
        0,
      ),
    ).toBe('5:00 PM');
    night.value = '19:30';
    night.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    at(switches(target), 4).click();
    await settle();
    expect(saves).toEqual([
      { threshold: 70 },
      { status: false },
      { night_before: true },
      { night_time: '19:30' },
      { quiet_from: '00:00', quiet_to: '00:00' },
    ]);
    expect(target.textContent).not.toContain('Chance alerts only');
    expect(target.querySelector('[role="status"]')?.textContent.trim()).toBe('Saved');
  });

  it('flips a choice back when it does not save', async () => {
    const { client } = fakeClient({ save: () => Promise.reject(new Error('offline')) }, 1, true);
    const target = await show(client, 'supported');
    const status = at(switches(target), 1);
    expect(status.checked).toBe(true);
    status.click();
    await settle();
    expect(status.checked).toBe(true);
    expect(target.querySelector('[role="status"]')?.textContent.trim()).toBe('Try again');
  });

  it('says so when there is no saved school', async () => {
    const target = await show(fakeClient().client, 'supported', 0);
    expect(target.textContent).toContain('Save a school first');
  });
});
