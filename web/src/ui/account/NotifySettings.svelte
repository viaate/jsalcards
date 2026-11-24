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
  import { connectedAs, quietNote, settingTime, thresholdName, tripsCopy } from '../../copy-trips';
  import {
    createTripsClient,
    localDay,
    type FlightsNotify,
    type GoogleState,
    type TripsClient,
  } from '../../modes/flights/trips';

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
  /** The iPhone steps, opened from the "How" link. */
  let howOpen = $state(false);
  /** The Flights group (flights spec D3, D12): its own choices beside the Schools ones. */
  let trips = $state<TripsClient | null>(null);
  let flights = $state<FlightsNotify | null>(null);
  /** Google, when the owner has set it up: email is offered only while it is connected. */
  let google = $state<GoogleState | null>(null);

  async function saveFlights(change: Partial<FlightsNotify>): Promise<void> {
    if (trips === null) return;
    try {
      flights = await trips.setNotify(change);
    } catch {
      failed = 'failed';
    }
  }

  onMount(() => {
    const flightsClient = createTripsClient(store);
    trips = flightsClient;
    void flightsClient.notify().then(
      (read) => {
        flights = read;
      },
      () => undefined,
    );
    void flightsClient.googleConfig().then(async (config) => {
      if (!config.configured) return;
      google = await flightsClient.google().catch(() => null);
    });
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
  /** This device, for the Flights group: what it is, and whether this page can turn it on. */
  const blocked = $derived(permission === 'denied' || failed === 'blocked');
  const deviceWord = $derived(
    deviceOn
      ? tripsCopy.notify.deviceOn
      : can === 'unsupported'
        ? notifyCopy.settings.unsupported
        : can === 'ios-install'
          ? notifyCopy.ios.title
          : blocked
            ? tripsCopy.notify.deviceBlocked
            : tripsCopy.notify.deviceOff,
  );
  const deviceHint = $derived(
    deviceOn
      ? null
      : can === 'unsupported' || can === 'ios-install'
        ? tripsCopy.notify.cannotHint
        : blocked
          ? tripsCopy.notify.blockedHint
          : tripsCopy.notify.offHint,
  );
  const canTurnOn = $derived(
    !deviceOn && !blocked && can !== 'unsupported' && can !== 'ios-install',
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

  /** The header switch: on asks the browser, off stops this device; it then shows what is so. */
  async function flipDevice(event: Event): Promise<void> {
    const input = event.currentTarget as HTMLInputElement;
    await (input.checked ? turnOn() : turnOff());
    input.checked = deviceOn;
  }

  /** A choice's switch: saved as it flips, then it shows what was saved. */
  async function flip(
    event: Event,
    change: (on: boolean) => Partial<NotifySettings>,
    shown: () => boolean,
  ): Promise<void> {
    const input = event.currentTarget as HTMLInputElement;
    await save(change(input.checked));
    input.checked = shown();
  }

  function chosen(event: Event): string {
    return (event.currentTarget as HTMLSelectElement).value;
  }
</script>

<section class="notify" aria-labelledby="notify-title">
  <div class="group">
    <div class="row head">
      <h3 class="label" id="notify-title">{notifyCopy.settings.title}</h3>
      <span class="state" class:error={failed === 'failed'} role="status"
        >{#if failed === 'failed'}{notifyCopy.settings
            .failed}{:else if note === 'saving'}{notifyCopy.settings
            .saving}{:else if note === 'saved'}{notifyCopy.settings.saved}{/if}</span
      >
      {#if can === 'ios-install'}
        <!-- The row under this one says what to do first. -->
      {:else if can === 'unsupported'}
        <span class="value">{notifyCopy.settings.unsupported}</span>
      {:else if permission === 'denied' || failed === 'blocked'}
        <span class="value">{notifyCopy.settings.blocked}</span>
      {:else}
        <input
          class="switch"
          type="checkbox"
          role="switch"
          aria-label={notifyCopy.settings.device}
          checked={deviceOn}
          disabled={busy}
          onchange={(event) => void flipDevice(event)}
        />
      {/if}
    </div>

    {#if can === 'ios-install'}
      <button
        class="row nav"
        class:open={howOpen}
        type="button"
        data-testid="ios-guide"
        aria-expanded={howOpen}
        aria-controls="ios-steps"
        onclick={() => (howOpen = !howOpen)}
      >
        <span class="label">{notifyCopy.ios.title}</span>
        <span class="value">{notifyCopy.ios.how}</span>
        <svg class="chevron" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M6 3.5l4.5 4.5L6 12.5" />
        </svg>
      </button>
      {#if howOpen}
        <ol class="steps" id="ios-steps">
          {#each notifyCopy.ios.steps as step (step)}
            <li>{step}</li>
          {/each}
        </ol>
      {/if}
    {/if}

    {#if schools === 0}
      <!-- With the Flights group below, the note says it is about school alerts only. -->
      <div class="row">
        <span class="label dim"
          >{flights === null ? notifyCopy.settings.noSchools : tripsCopy.notify.noSchools}</span
        >
      </div>
    {/if}

    {#if current !== null && (deviceOn || current.devices > 0)}
      <label class="row">
        <span class="label">{notifyCopy.settings.status}</span>
        <input
          class="switch"
          type="checkbox"
          role="switch"
          checked={current.settings.status}
          onchange={(event) =>
            void flip(
              event,
              (on) => ({ status: on }),
              () => current?.settings.status ?? false,
            )}
        />
      </label>

      <label class="row">
        <span class="label">{notifyCopy.settings.chance}</span>
        <input
          class="switch"
          type="checkbox"
          role="switch"
          checked={current.settings.chance}
          onchange={(event) =>
            void flip(
              event,
              (on) => ({ chance: on }),
              () => current?.settings.chance ?? false,
            )}
        />
      </label>
      {#if current.settings.chance}
        <div class="row sub">
          <div class="segments" role="radiogroup" aria-label={notifyCopy.settings.threshold}>
            {#each THRESHOLDS as value (value)}
              <label class="segment" class:on={current.settings.threshold === value}>
                <input
                  type="radio"
                  name="notify-threshold"
                  value={String(value)}
                  checked={current.settings.threshold === value}
                  onchange={() => void save({ threshold: value })}
                />
                <span>{notifyFormat.threshold(value)}</span>
              </label>
            {/each}
          </div>
        </div>
      {/if}

      <label class="row">
        <span class="label">{notifyCopy.settings.night}</span>
        <input
          class="switch"
          type="checkbox"
          role="switch"
          checked={current.settings.night_before}
          onchange={(event) =>
            void flip(
              event,
              (on) => ({ night_before: on }),
              () => current?.settings.night_before ?? false,
            )}
        />
      </label>
      {#if current.settings.night_before}
        <label class="row sub">
          <span class="label dim">{notifyCopy.settings.nightTime}</span>
          <span class="pick">
            <span class="shown" aria-hidden="true"
              >{notifyFormat.hour(current.settings.night_time)}</span
            >
            <select
              value={current.settings.night_time}
              onchange={(event) => void save({ night_time: chosen(event) })}
            >
              {#each NIGHT_TIMES as value (value)}
                <option {value}>{notifyFormat.hour(value)}</option>
              {/each}
            </select>
          </span>
        </label>
      {/if}

      <label class="row">
        <span class="label">{notifyCopy.settings.quiet}</span>
        <input
          class="switch"
          type="checkbox"
          role="switch"
          checked={quietOn}
          onchange={(event) =>
            void flip(
              event,
              (on) => (on ? DEFAULT_QUIET : { quiet_from: '00:00', quiet_to: '00:00' }),
              () => quietOn,
            )}
        />
      </label>
      {#if quietOn}
        <div class="row sub">
          <span class="label dim">{notifyCopy.settings.quietHolds}</span>
          <span class="range">
            <span class="pick">
              <span class="shown" aria-hidden="true"
                >{notifyFormat.hour(current.settings.quiet_from)}</span
              >
              <select
                aria-label={notifyCopy.settings.quietFrom}
                value={current.settings.quiet_from}
                onchange={(event) => void save({ quiet_from: chosen(event) })}
              >
                {#each HOURS as value (value)}
                  <option {value}>{notifyFormat.hour(value)}</option>
                {/each}
              </select>
            </span>
            <span class="dash" aria-hidden="true">–</span>
            <span class="pick">
              <span class="shown" aria-hidden="true"
                >{notifyFormat.hour(current.settings.quiet_to)}</span
              >
              <select
                aria-label={notifyCopy.settings.quietTo}
                value={current.settings.quiet_to}
                onchange={(event) => void save({ quiet_to: chosen(event) })}
              >
                {#each HOURS as value (value)}
                  <option {value}>{notifyFormat.hour(value)}</option>
                {/each}
              </select>
            </span>
          </span>
        </div>
      {/if}
    {/if}
  </div>

  {#if flights !== null}
    <div class="group" data-testid="notify-flights">
      <div class="row head">
        <h3 class="label">{tripsCopy.notify.title}</h3>
      </div>
      <label class="row">
        <span class="label">{tripsCopy.notify.alerts}</span>
        <input
          class="switch"
          type="checkbox"
          role="switch"
          checked={flights.alerts}
          onchange={(event) => void saveFlights({ alerts: event.currentTarget.checked })}
        />
      </label>
      {#if flights.alerts}
        <div class="row" data-testid="flights-device">
          <span class="label">{tripsCopy.notify.device}</span>
          <span class="value">{deviceWord}</span>
        </div>
        {#if deviceHint !== null}
          <div class="row sub"><span class="label dim">{deviceHint}</span></div>
        {/if}
        {#if canTurnOn}
          <button
            class="row action positive"
            type="button"
            disabled={busy}
            onclick={() => void turnOn()}
            data-testid="flights-turn-on"
          >
            <span class="label">{tripsCopy.notify.turnOn}</span>
          </button>
        {/if}
        <div class="row">
          <span class="label" id="flights-threshold-label">{tripsCopy.notify.threshold}</span>
          <div class="segments" role="radiogroup" aria-labelledby="flights-threshold-label">
            {#each [30, 50, 70] as const as value (value)}
              <label class="segment" class:on={flights.threshold === value}>
                <input
                  type="radio"
                  name="flights-threshold"
                  value={String(value)}
                  checked={flights.threshold === value}
                  onchange={() => void saveFlights({ threshold: value })}
                />
                <span>{thresholdName(value)}</span>
              </label>
            {/each}
          </div>
        </div>
        <div class="row sub"><span class="label dim">{tripsCopy.notify.thresholdHint}</span></div>
        <label class="row">
          <span class="label">{tripsCopy.notify.night}</span>
          <input
            class="switch"
            type="checkbox"
            role="switch"
            checked={flights.night_before}
            onchange={(event) => void saveFlights({ night_before: event.currentTarget.checked })}
          />
        </label>
        {#if flights.night_before}
          <label class="row sub">
            <span class="label dim">{tripsCopy.notify.nightTime}</span>
            <span class="pick">
              <span class="shown" aria-hidden="true">{settingTime(flights.night_time)}</span>
              <select
                value={flights.night_time}
                onchange={(event) => void saveFlights({ night_time: chosen(event) })}
                data-testid="flights-night-time"
              >
                {#each NIGHT_TIMES as value (value)}
                  <option {value}>{settingTime(value)}</option>
                {/each}
              </select>
            </span>
          </label>
        {/if}
        {#if current !== null && quietOn}
          <div class="row sub">
            <span class="label dim"
              >{quietNote(
                settingTime(current.settings.quiet_from),
                settingTime(current.settings.quiet_to),
              )}</span
            >
          </div>
        {/if}
        {#if google?.connected === true && google.send === true}
          <label class="row">
            <span class="label">{tripsCopy.notify.email}</span>
            <input
              class="switch"
              type="checkbox"
              role="switch"
              checked={flights.email}
              onchange={(event) => void saveFlights({ email: event.currentTarget.checked })}
            />
          </label>
          <div class="row sub"><span class="label dim">{tripsCopy.notify.emailHint}</span></div>
          <!-- When it was connected: a Google client in Testing mode ends its link after 7 days. -->
          <div class="row sub">
            <span class="label dim">{connectedAs(google.email ?? '', localDay(google.since))}</span>
          </div>
        {:else if google !== null}
          <div class="row sub"><span class="label dim">{tripsCopy.notify.emailOff}</span></div>
        {/if}
      {/if}
    </div>
  {/if}

  {#if current !== null && current.devices > 0}
    <div class="group">
      <button class="row action" type="button" disabled={busy} onclick={turnOffAll}>
        <span class="label">{notifyCopy.settings.turnOffAll}</span>
        <span class="value">{notifyFormat.devices(current.devices)}</span>
      </button>
    </div>
  {/if}
</section>

<style>
  /* The settings group, then Turn off everywhere in its own group under it. */
  .notify {
    display: flex;
    flex: none;
    flex-direction: column;
    gap: 16px;
  }

  .head {
    min-height: 52px;
  }

  h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .state {
    flex: none;
    font-size: 13px;
    color: var(--text-3);
  }

  .state:empty {
    display: none;
  }

  .state.error {
    color: var(--status-delayed);
  }

  .dim {
    color: var(--text-2);
  }

  /* An iOS switch in Snowlight's colors: a white knob always, on a flat ice-blue track when on
     (the closed hue, as on Call it's chosen Snow day) and a dark gray one when off. */
  .switch {
    position: relative;
    flex: none;
    width: 46px;
    height: 28px;
    margin: 0;
    cursor: pointer;
    background: color-mix(in srgb, var(--text-1) 22%, var(--surface-2));
    border-radius: 14px;
    transition: background 140ms ease;
    appearance: none;
  }

  .switch::after {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 24px;
    height: 24px;
    content: '';
    background: #fff;
    border-radius: 50%;
    transition: transform 140ms ease;
  }

  .switch:checked {
    background: var(--status-closed);
  }

  .switch:checked::after {
    transform: translateX(18px);
  }

  .switch:disabled {
    cursor: default;
    opacity: 0.5;
  }

  .switch:focus-visible,
  .nav:focus-visible,
  .segment:has(input:focus-visible) {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  /* A sub-row: a muted label, then its value (the 30% | 50% | 70% choice, a time, a range). */
  .sub {
    gap: 8px;
    min-height: 0;
    padding-top: 2px;
    padding-bottom: 12px;
  }

  .segments {
    display: flex;
    flex: 1;
    padding: 3px;
    border: 1px solid var(--border-2);
    border-radius: 999px;
  }

  .segment {
    position: relative;
    display: grid;
    flex: 1;
    place-items: center;
    height: 30px;
    font-size: 14px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-2);
    cursor: pointer;
    border-radius: 999px;
  }

  .segment.on {
    color: var(--bg);
    background: var(--text-1);
  }

  .segment input {
    position: absolute;
    inset: 0;
    margin: 0;
    opacity: 0;
    cursor: pointer;
  }

  /* A time as a compact gray value, the browser's own picker over it: tap it to change it. */
  .pick {
    position: relative;
    display: inline-flex;
    flex: none;
    align-items: center;
    height: 30px;
    padding: 0 8px;
    background: color-mix(in srgb, var(--text-1) 10%, var(--surface-2));
    border-radius: 7px;
  }

  .pick:has(select:focus-visible) {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  .shown {
    font-size: 15px;
    font-variant-numeric: tabular-nums;
    color: var(--text-1);
    white-space: nowrap;
  }

  .pick select {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    /* 16px keeps iPhone Safari from zooming in on it. */
    font: inherit;
    font-size: 16px;
    cursor: pointer;
    opacity: 0;
    appearance: none;
  }

  .range {
    display: inline-flex;
    flex: none;
    gap: 4px;
    align-items: center;
  }

  .dash {
    color: var(--text-3);
  }

  /* A 375-wide phone keeps "Chance alerts only" and both times on one line. */
  @media (max-width: 389px) {
    .pick {
      padding: 0 6px;
    }

    .range {
      gap: 2px;
    }
  }

  /* A row that opens what is under it: its value muted, then a chevron that turns down. */
  .nav {
    width: 100%;
    font: inherit;
    font-size: 15px;
    text-align: left;
    cursor: pointer;
    background: none;
    border: 0;
  }

  .nav:hover {
    background: color-mix(in srgb, var(--text-1) 4%, transparent);
  }

  .chevron {
    flex: none;
    width: 14px;
    height: 14px;
    margin-left: -6px;
    fill: none;
    stroke: var(--text-3);
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 140ms ease;
  }

  .nav.open .chevron {
    transform: rotate(90deg);
  }

  .steps {
    margin: 0;
    padding: 12px 16px 14px 32px;
    font-size: 14px;
    line-height: 22px;
    color: var(--text-1);
  }

  .steps li::marker {
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .action {
    width: 100%;
    font: inherit;
    font-size: 15px;
    text-align: left;
    cursor: pointer;
    background: none;
    border: 0;
  }

  .action .label {
    color: var(--destructive);
  }

  .action.positive .label {
    color: var(--text-1);
    font-weight: 600;
  }

  .action:disabled {
    cursor: default;
    opacity: 0.6;
  }

  .action:hover:not(:disabled),
  .action:focus-visible {
    background: color-mix(in srgb, var(--text-1) 4%, transparent);
    outline: none;
  }
</style>
