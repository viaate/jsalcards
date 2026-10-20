<script lang="ts">
  import { onDestroy, onMount } from 'svelte';

  import type { Services } from '../app/boot';
  import type { SchoolView } from '../app/school';
  import { accountFormat, adminCopy } from '../copy-account';
  import { fetchJson } from '../data/files';
  import { parsePredictions } from '../data/school-day';
  import { stateOfId } from '../text/school-names';
  import { PUBLISHED_PATHS, type PredictionsFile } from '../types/generated';
  import type { AdminCall, ManualStatus } from './call';
  import { STATE_ZONES, endOfLocalDay, showsToday } from './overview';

  interface Props {
    call: AdminCall;
    app: Services | null;
  }

  let { call, app }: Props = $props();

  type StatusName = 'closed' | 'delayed' | 'early_dismissal' | 'open';
  const STATUS_NAMES: readonly StatusName[] = ['closed', 'delayed', 'early_dismissal', 'open'];
  const STATUS_WORDS = {
    closed: adminCopy.statuses.closed,
    delayed: adminCopy.statuses.delayed,
    early_dismissal: adminCopy.statuses.earlyDismissal,
    open: adminCopy.statuses.open,
  } as const;

  interface Picked {
    readonly kind: 'school' | 'district';
    readonly id: string;
    readonly name: string;
    readonly state: string;
  }

  let query = $state('');
  /** A school or district to pick: from search, or typed as its id. */
  interface Option {
    readonly kind: 'school' | 'district';
    readonly id: string;
    readonly name: string;
    readonly sub: string;
    readonly state: string;
  }

  let results = $state<Option[]>([]);
  let picked = $state.raw<Picked | null>(null);
  /** The district the pick is in (itself for a district). */
  let districtId = $state<string | null>(null);
  /** A school whose panel shows what the map shows for the pick. */
  let view = $state<SchoolView | null>(null);
  let timeZone = $state<string | null>(null);

  let scope = $state<'district' | 'school'>('district');
  let status = $state<StatusName>('closed');
  let minutes = $state(120);
  let time = $state('12:00');
  let until = $state<'today' | 'tomorrow'>('today');
  let note = $state('');
  let busy = $state(false);
  /** A pick's district, zone and map line are still being read. */
  let resolving = $state(false);
  let failed = $state(false);

  let list = $state<ManualStatus[] | null>(null);
  /** Which active manual statuses the map shows, by key. */
  let shown = $state<Record<string, boolean>>({});
  /** Names picked here, by key, for the list. */
  let names = $state<Record<string, string>>({});

  let predictions: Promise<PredictionsFile | null> | null = null;
  let stopView: () => void = () => undefined;
  /** What stops each watch of the map, by manual status and status (not shown, so not reactive). */
  const watchers: Record<string, () => void> = {};
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let pollTimer: ReturnType<typeof setInterval> | undefined;

  function readPredictions(services: Services): Promise<PredictionsFile | null> {
    predictions ??= (async () => {
      const files = services.data.files;
      if (!files.has(PUBLISHED_PATHS.predictions)) return null;
      try {
        return parsePredictions(
          await fetchJson(files, PUBLISHED_PATHS.predictions, { cache: 'no-cache' }),
        );
      } catch {
        return null;
      }
    })();
    return predictions;
  }

  /** A district's LEAID or a public school's id, typed whole: picked by its id alone. */
  function typedId(text: string): Option | null {
    const kind = /^\d{7}$/.test(text) ? 'district' : /^\d{12}$/.test(text) ? 'school' : null;
    const state = stateOfId(text);
    if (kind === null || state === null) return null;
    return { kind, id: text, name: accountFormat.target(kind, text), sub: '', state };
  }

  function onInput(): void {
    clearTimeout(searchTimer);
    const text = query.trim();
    const typed = typedId(text);
    results = typed === null ? [] : [typed];
    if (text.length < 2 || app === null) return;
    const services = app;
    searchTimer = setTimeout(() => {
      void services.lookup(text).then((found) => {
        if (query.trim() !== text) return;
        const hits: Option[] = [];
        for (const hit of found?.schools ?? []) {
          if (hit.kind !== 'school' && hit.kind !== 'district') continue;
          if (typed?.id === hit.id) continue;
          hits.push({ kind: hit.kind, id: hit.id, name: hit.name, sub: hit.sub, state: hit.state });
        }
        results = [...(typed === null ? [] : [typed]), ...hits].slice(0, 8);
      });
    }, 150);
  }

  async function pick(hit: Option): Promise<void> {
    if (app === null) return;
    const services = app;
    const next: Picked = { kind: hit.kind, id: hit.id, name: hit.name, state: hit.state };
    picked = next;
    query = '';
    results = [];
    scope = 'district';
    view = null;
    districtId = null;
    timeZone = STATE_ZONES[hit.state] ?? null;
    stopView();
    // Until its district and zone are read, the form waits: a status is never set for less.
    resolving = true;
    try {
      await resolve(services, hit, next);
    } finally {
      if (picked === next) resolving = false;
    }
  }

  async function resolve(services: Services, hit: Option, next: Picked): Promise<void> {
    const directory = await (await services.data.directories())?.get();
    if (picked !== next) return;
    let anchor: string | null;
    if (hit.kind === 'district') {
      districtId = hit.id;
      anchor = await services.schoolOf(hit.id);
    } else {
      anchor = hit.id;
      const index = directory?.schoolIndex(hit.id) ?? -1;
      const district = index >= 0 ? (directory?.district[index] ?? -1) : -1;
      districtId = district >= 0 ? (directory?.meta.districts.ids[district] ?? null) : null;
      // A public school's id starts with its district's (NCES: LEAID, then a school number).
      if (districtId === null && /^\d{12}$/.test(hit.id)) districtId = hit.id.slice(0, 7);
      if (districtId === null) scope = 'school';
    }
    if (picked !== next) return;
    // The school's own day: its district's time zone, from the predictions file.
    const file = await readPredictions(services);
    const target = districtId === null ? -1 : (directory?.districtIndex(districtId) ?? -1);
    const zone = file?.districts.find((d) => d.district === target)?.time_zone;
    if (picked === next && zone !== undefined) timeZone = zone;
    if (anchor !== null && picked === next) {
      stopView = services.watchSchool(anchor, null, (next) => {
        view = next;
      });
    }
  }

  function expiry(): string | null {
    if (timeZone === null) return null;
    try {
      return endOfLocalDay(new Date(), timeZone, until === 'today' ? 0 : 1).toISOString();
    } catch {
      return null;
    }
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (picked === null || busy) return;
    const id = scope === 'district' ? districtId : picked.kind === 'school' ? picked.id : null;
    const expires = expiry();
    if (id === null || expires === null) {
      failed = true;
      return;
    }
    busy = true;
    failed = false;
    try {
      await call('PUT', '/v1/admin/overrides', {
        scope,
        id,
        status,
        minutes: status === 'delayed' ? minutes : null,
        at_local_time: status === 'early_dismissal' ? time : null,
        note: note.trim() === '' ? null : note.trim(),
        expires_at: expires,
      });
      names = {
        ...names,
        [`${scope}:${id}`]:
          scope === 'district' && picked.kind === 'school'
            ? (view?.place ?? picked.name)
            : picked.name,
      };
      note = '';
      await load();
    } catch {
      failed = true;
    } finally {
      busy = false;
    }
  }

  async function clear(key: string): Promise<void> {
    busy = true;
    failed = false;
    try {
      await call('DELETE', `/v1/admin/overrides/${encodeURIComponent(key)}`);
      await load();
    } catch {
      failed = true;
    } finally {
      busy = false;
    }
  }

  /** Watches what the map shows for each active manual status. */
  function watch(items: readonly ManualStatus[]): void {
    const services = app;
    if (services === null) return;
    const wanted = new Set(items.filter((o) => o.active).map((o) => `${o.key}|${o.status}`));
    for (const [key, stop] of Object.entries(watchers)) {
      if (!wanted.has(key)) {
        stop();
        // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
        delete watchers[key];
      }
    }
    for (const item of items) {
      const watchKey = `${item.key}|${item.status}`;
      if (!item.active || watchKey in watchers) continue;
      let stopped = false;
      let stop: () => void = () => undefined;
      watchers[watchKey] = () => {
        stopped = true;
        stop();
      };
      void (item.scope === 'school' ? Promise.resolve(item.id) : services.schoolOf(item.id)).then(
        (anchor) => {
          if (stopped || anchor === null) return;
          stop = services.watchSchool(anchor, null, (next) => {
            shown = { ...shown, [item.key]: showsToday(next, item.status) };
          });
        },
      );
    }
  }

  async function load(): Promise<void> {
    try {
      const body = await call<{ overrides: ManualStatus[] }>('GET', '/v1/admin/overrides');
      list = body.overrides;
      watch(body.overrides);
    } catch {
      list = list ?? [];
      failed = true;
    }
  }

  onMount(() => {
    void load();
    pollTimer = setInterval(() => void load(), 60_000);
  });

  $effect(() => {
    if (app !== null && list !== null) watch(list);
  });

  onDestroy(() => {
    clearTimeout(searchTimer);
    clearInterval(pollTimer);
    stopView();
    for (const stop of Object.values(watchers)) stop();
  });

  const active = $derived((list ?? []).filter((o) => o.active));
  const today = $derived(view?.status.filter((line) => line.headline !== '') ?? []);
</script>

<section>
  <h3>{adminCopy.statuses.find}</h3>
  <input
    class="find"
    type="search"
    bind:value={query}
    oninput={onInput}
    aria-label={adminCopy.statuses.find}
    placeholder={adminCopy.statuses.find}
    autocomplete="off"
  />
  {#if results.length > 0}
    <ul class="results">
      {#each results as hit (hit.kind + hit.id)}
        <li>
          <button type="button" onclick={() => void pick(hit)}>
            <span>{hit.name}</span>
            {#if hit.sub !== ''}<span class="muted">{hit.sub}</span>{/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

{#if picked !== null}
  <section>
    <h3>{picked.name}</h3>
    <p class="muted">{adminCopy.statuses.published}</p>
    {#if view === null || view.loading}
      <p class="muted">{adminCopy.overview.loading}</p>
    {:else if today.length === 0}
      <p>{adminCopy.statuses.nothing}</p>
    {:else}
      <ul class="lines">
        {#each today as line, i (i)}
          <li>
            {line.headline}{#if line.detail !== null}<span class="muted">
                · {line.detail}</span
              >{/if}
          </li>
        {/each}
      </ul>
    {/if}
    {#if view?.chance}
      <p class="muted">{adminCopy.statuses.chance} · {view.chance.number}</p>
    {/if}

    <form class="set" onsubmit={submit}>
      <h3>{adminCopy.statuses.set}</h3>
      {#if picked.kind === 'school' && districtId !== null}
        <fieldset>
          <legend>{adminCopy.statuses.scope}</legend>
          <label
            ><input type="radio" bind:group={scope} value="district" />{adminCopy.statuses
              .district}</label
          >
          <label
            ><input type="radio" bind:group={scope} value="school" />{adminCopy.statuses
              .school}</label
          >
        </fieldset>
      {/if}
      <fieldset>
        <legend>{adminCopy.statuses.status}</legend>
        {#each STATUS_NAMES as name (name)}
          <label><input type="radio" bind:group={status} value={name} />{STATUS_WORDS[name]}</label>
        {/each}
      </fieldset>
      {#if status === 'delayed'}
        <label class="field">
          <span>{adminCopy.statuses.minutes}</span>
          <input type="number" min="1" max="240" step="1" bind:value={minutes} required />
        </label>
      {:else if status === 'early_dismissal'}
        <label class="field">
          <span>{adminCopy.statuses.time}</span>
          <input type="time" bind:value={time} required />
        </label>
      {/if}
      <label class="field">
        <span>{adminCopy.statuses.until}</span>
        <select bind:value={until}>
          <option value="today">{adminCopy.statuses.endToday}</option>
          <option value="tomorrow">{adminCopy.statuses.endTomorrow}</option>
        </select>
      </label>
      <label class="field">
        <span>{adminCopy.statuses.note}</span>
        <input type="text" maxlength="200" bind:value={note} />
      </label>
      <button class="button primary" type="submit" disabled={busy || resolving}
        >{adminCopy.statuses.save}</button
      >
    </form>
  </section>
{/if}

{#if failed}<p class="error" role="alert">{adminCopy.errors.failed}</p>{/if}

<section>
  <h3>{adminCopy.statuses.active}</h3>
  {#if list === null}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if active.length === 0}
    <p class="muted">{adminCopy.statuses.noneActive}</p>
  {:else}
    <div class="scroll">
      <table>
        <tbody>
          {#each active as item (item.key)}
            <tr>
              <td>
                {names[item.key] ?? accountFormat.target(item.scope, item.id)}
                {#if item.note !== null}<div class="muted">{item.note}</div>{/if}
              </td>
              <td>{accountFormat.manualStatus(item.status, item.minutes, item.at_local_time)}</td>
              <td class="muted">{adminCopy.statuses.until} {accountFormat.when(item.expires_at)}</td
              >
              <td
                >{shown[item.key] === true
                  ? adminCopy.statuses.onMap
                  : adminCopy.statuses.waiting}</td
              >
              <td>
                <button
                  class="button"
                  type="button"
                  disabled={busy}
                  onclick={() => void clear(item.key)}>{adminCopy.statuses.clear}</button
                >
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  .find {
    width: min(100%, 420px);
  }

  .results {
    max-width: 420px;
    margin: 6px 0 0;
    padding: 4px;
    list-style: none;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 10px;
  }

  .results button {
    display: flex;
    flex-direction: column;
    width: 100%;
    padding: 8px 10px;
    font: inherit;
    font-size: 14px;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    background: none;
    border: 0;
    border-radius: 8px;
  }

  .results button:hover,
  .results button:focus-visible {
    background: var(--surface-2);
    outline: none;
  }

  .results .muted {
    font-size: 12px;
  }

  .lines {
    margin: 0 0 8px;
    padding-left: 18px;
    font-size: 14px;
  }

  .set {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-width: 420px;
    margin-top: 20px;
  }

  fieldset {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
    margin: 0;
    padding: 0;
    border: 0;
  }

  legend {
    margin-bottom: 6px;
    font-size: 13px;
    color: var(--text-2);
  }

  fieldset label {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 14px;
  }

  fieldset input {
    height: auto;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--text-2);
  }
</style>
