<script lang="ts">
  import { onMount } from 'svelte';

  import {
    THRESHOLDS,
    createNotifyClient,
    support as browserSupport,
    type NotifyClient,
    type NotifySettings,
    type NotifyState,
    type Support,
  } from '../../account/notify';
  import type { AccountStore } from '../../account/session';
  import { notifyCopy, notifyFormat } from '../../copy-notify';

  interface Props {
    store: AccountStore;
    /** How many schools the account saves (the settings note says when there are none). */
    schools: number;
    /** Tests hand in a client and what the browser can do. */
    client?: NotifyClient;
    support?: Support;
  }

  let { store, schools, client: given, support: supportGiven }: Props = $props();

  const NIGHT_TIMES = [
    '17:00',
    '17:30',
    '18:00',
    '18:30',
    '19:00',
    '19:30',
    '20:00',
    '20:30',
    '21:00',
    '21:30',
  ];
  const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`);
  const DEFAULT_QUIET = { quiet_from: '22:00', quiet_to: '05:00' } as const;

  let client = $state<NotifyClient>();
  let can = $state<Support>('unsupported');
  let permission = $state<NotificationPermission | null>(null);
  let deviceOn = $state(false);
  let current = $state<NotifyState | null>(null);
  let busy = $state(false);
  let failed = $state<'failed' | 'blocked' | null>(null);
  let note = $state<'saving' | 'saved' | null>(null);

  onMount(() => {
    client =
      given ??
      createNotifyClient(
        store.api,
        () => store.token(),
        () => store.state.user?.id ?? null,
      );
    can = supportGiven ?? browserSupport();
    permission = client.permission();
    void client.isOn().then((on) => (deviceOn = on));
    void client
      .read()
      .then((found) => (current = found))
      .catch(() => undefined);
  });

  const quietOn = $derived(
    current !== null && current.settings.quiet_from !== current.settings.quiet_to,
  );

  async function turnOn(): Promise<void> {
    if (client === undefined || busy) return;
    busy = true;
    failed = null;
    try {
      const result = await client.turnOn();
      permission = client.permission();
      if (result === 'on') {
        deviceOn = true;
        current = await client.read().catch(() => current);
      } else if (result === 'blocked') failed = 'blocked';
      else failed = 'failed';
    } catch {
      failed = 'failed';
    } finally {
      busy = false;
    }
  }

  async function turnOff(): Promise<void> {
    if (client === undefined || busy) return;
    busy = true;
    failed = null;
    try {
      await client.turnOff();
      deviceOn = false;
      current = await client.read().catch(() => current);
    } catch {
      failed = 'failed';
    } finally {
      busy = false;
    }
  }

  async function turnOffAll(): Promise<void> {
    if (client === undefined || busy || current === null) return;
    busy = true;
    failed = null;
    try {
      const devices = await client.turnOffAll();
      deviceOn = false;
      current = { ...current, devices };
    } catch {
      failed = 'failed';
    } finally {
      busy = false;
    }
  }

  async function save(change: Partial<NotifySettings>): Promise<void> {
    if (client === undefined) return;
    note = 'saving';
    failed = null;
    try {
      current = await client.save(change);
      note = 'saved';
    } catch {
      note = null;
      failed = 'failed';
    }
  }

  function checked(event: Event): boolean {
    return (event.currentTarget as HTMLInputElement).checked;
  }

  function chosen(event: Event): string {
    return (event.currentTarget as HTMLSelectElement).value;
  }
</script>

<section class="notify" aria-labelledby="notify-title">
  <h3 id="notify-title">{notifyCopy.settings.title}</h3>
  <p class="note">{notifyCopy.settings.intro}</p>

  {#if can === 'ios-install'}
    <div class="ios" data-testid="ios-guide">
      <p class="ios-title">{notifyCopy.ios.title}</p>
      <ol>
        {#each notifyCopy.ios.steps as step (step)}
          <li>{step}</li>
        {/each}
      </ol>
      <p class="note">{notifyCopy.ios.note}</p>
    </div>
  {:else if can === 'unsupported'}
    <p class="note">{notifyCopy.settings.unsupported}</p>
  {:else if permission === 'denied' || failed === 'blocked'}
    <p class="note">{notifyCopy.settings.blocked}</p>
  {:else if deviceOn}
    <p class="note">{notifyCopy.settings.on}</p>
    <button class="secondary" type="button" disabled={busy} onclick={turnOff}>
      {busy ? notifyCopy.settings.working : notifyCopy.settings.turnOff}
    </button>
  {:else}
    <button class="primary" type="button" disabled={busy} onclick={turnOn}>
      {busy ? notifyCopy.settings.working : notifyCopy.settings.turnOn}
    </button>
  {/if}

  {#if schools === 0}
    <p class="note">{notifyCopy.settings.noSchools}</p>
  {/if}

  {#if current !== null && (deviceOn || current.devices > 0)}
    <fieldset>
      <legend>{notifyCopy.settings.choices}</legend>
      <label class="check">
        <input
          type="checkbox"
          checked={current.settings.status}
          onchange={(event) => void save({ status: checked(event) })}
        />
        <span>{notifyCopy.settings.status}</span>
      </label>
      <p class="note indent">{notifyCopy.settings.statusNote}</p>

      <label class="check">
        <input
          type="checkbox"
          checked={current.settings.chance}
          onchange={(event) => void save({ chance: checked(event) })}
        />
        <span>{notifyCopy.settings.chance}</span>
      </label>
      {#if current.settings.chance}
        <label class="pick indent">
          <span>{notifyCopy.settings.threshold}</span>
          <select
            value={String(current.settings.threshold)}
            onchange={(event) =>
              void save({ threshold: Number(chosen(event)) as NotifySettings['threshold'] })}
          >
            {#each THRESHOLDS as value (value)}
              <option value={String(value)}>{notifyFormat.threshold(value)}</option>
            {/each}
          </select>
        </label>
      {/if}

      <label class="check">
        <input
          type="checkbox"
          checked={current.settings.night_before}
          onchange={(event) => void save({ night_before: checked(event) })}
        />
        <span>{notifyCopy.settings.night}</span>
      </label>
      <p class="note indent">{notifyCopy.settings.nightNote}</p>
      {#if current.settings.night_before}
        <label class="pick indent">
          <span>{notifyCopy.settings.nightTime}</span>
          <select
            value={current.settings.night_time}
            onchange={(event) => void save({ night_time: chosen(event) })}
          >
            {#each NIGHT_TIMES as value (value)}
              <option {value}>{notifyFormat.hour(value)}</option>
            {/each}
          </select>
        </label>
      {/if}

      <label class="check">
        <input
          type="checkbox"
          checked={quietOn}
          onchange={(event) =>
            void save(checked(event) ? DEFAULT_QUIET : { quiet_from: '00:00', quiet_to: '00:00' })}
        />
        <span>{notifyCopy.settings.quiet}</span>
      </label>
      <p class="note indent">{notifyCopy.settings.quietNote}</p>
      {#if quietOn}
        <div class="indent row">
          <label class="pick">
            <span>{notifyCopy.settings.quietFrom}</span>
            <select
              value={current.settings.quiet_from}
              onchange={(event) => void save({ quiet_from: chosen(event) })}
            >
              {#each HOURS as value (value)}
                <option {value}>{notifyFormat.hour(value)}</option>
              {/each}
            </select>
          </label>
          <label class="pick">
            <span>{notifyCopy.settings.quietTo}</span>
            <select
              value={current.settings.quiet_to}
              onchange={(event) => void save({ quiet_to: chosen(event) })}
            >
              {#each HOURS as value (value)}
                <option {value}>{notifyFormat.hour(value)}</option>
              {/each}
            </select>
          </label>
        </div>
      {/if}
      <p class="note">{notifyCopy.settings.zoneNote}</p>
    </fieldset>
  {/if}

  {#if current !== null && current.devices > 0}
    <div class="devices">
      <p class="note">{notifyFormat.devices(current.devices)}</p>
      <button class="secondary" type="button" disabled={busy} onclick={turnOffAll}>
        {busy ? notifyCopy.settings.working : notifyCopy.settings.turnOffAll}
      </button>
    </div>
  {/if}

  <p class="state" role="status">
    {#if failed === 'failed'}
      <span class="error">{notifyCopy.settings.failed}</span>
    {:else if note === 'saving'}
      {notifyCopy.settings.saving}
    {:else if note === 'saved'}
      {notifyCopy.settings.saved}
    {/if}
  </p>
</section>

<style>
  .notify {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-top: 16px;
    border-top: 1px solid var(--border-1);
  }

  h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }

  .devices {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }

  .note,
  .state {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
  }

  .state:empty {
    display: none;
  }

  .error {
    color: var(--status-delayed);
  }

  .ios {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 10px;
  }

  .ios-title {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-1);
  }

  ol {
    margin: 0;
    padding-left: 20px;
    font-size: 13px;
    line-height: 20px;
    color: var(--text-1);
  }

  fieldset {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 0;
    padding: 0;
    border: 0;
  }

  legend {
    margin-bottom: 4px;
    padding: 0;
    font-size: 13px;
    color: var(--text-2);
  }

  .check {
    display: flex;
    gap: 10px;
    align-items: center;
    font-size: 14px;
    color: var(--text-1);
  }

  .check input {
    width: 18px;
    height: 18px;
    margin: 0;
    accent-color: var(--text-1);
  }

  .indent {
    margin-left: 28px;
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }

  .pick {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 13px;
    color: var(--text-2);
  }

  select {
    height: 32px;
    padding: 0 8px;
    font: inherit;
    font-size: 13px;
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 8px;
  }

  select:focus-visible,
  .check input:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  button.primary,
  button.secondary {
    height: 40px;
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    border-radius: 10px;
  }

  button.primary {
    color: var(--bg);
    background: var(--text-1);
    border: 0;
  }

  button.secondary {
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
  }

  button:disabled {
    cursor: default;
    opacity: 0.6;
  }

  button:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }
</style>
