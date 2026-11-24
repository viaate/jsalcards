<!--
  My trips (flights spec D12, D21 pattern 6): the next trip big at the top with both codes and
  its usual times, later ones below as rows, past ones folded away. Each says its risk in the
  chance words, from the live file (gray and no word when the file is old, D7). Signed out, it
  says what trips are for and opens the sign-in. Connect Google, only once the owner has set
  Google up (dormant otherwise, D12): find flights in the calendar, and, with the demo flag only,
  in Gmail (D19), each shown for the person to confirm before it is saved.
-->
<script lang="ts">
  import { onMount } from 'svelte';

  import { flightName, routeName, updated, zoneName } from '../../copy-flights';
  import {
    TICKET_KEYS,
    percentName,
    connectedAs,
    foundName,
    legName,
    levelWord,
    ticketLine,
    ticketName,
    tripTitle,
    tripWhen,
    tripsCopy,
  } from '../../copy-trips';
  import PanelShell from '../../ui/PanelShell.svelte';
  import { instantOf } from './chance';
  import { revokeLeftover } from './gmail-leftover';
  import { clock } from '../../copy-flights';
  import { legLevel, tripPlan } from './backup';
  import { isStale } from './data';
  import type { Airport, FlightsFiles, LiveRead } from './data';
  import { fromCalendar, matchFound, type FoundFlight, type Match } from './found';
  import type { TripsHost } from './trips-host.svelte';
  import { localDay, takeGoogleReturn, type Trip } from './trips';

  interface Props {
    host: TripsHost;
    byCode: ReadonlyMap<string, Airport>;
    live: LiveRead | null;
    files: FlightsFiles;
    now: number;
    onopen: (trip: Trip) => void;
    onclose: () => void;
    onsettle: () => void;
  }

  let { host, byCode, live, files, now, onopen, onclose, onsettle }: Props = $props();

  const stale = $derived(isStale(live, now));
  let showPast = $state(false);

  const when = (trip: Trip): number => {
    const tz = byCode.get(trip.from)?.tz;
    return tz === undefined ? 0 : instantOf(trip.day, trip.leaves, tz).getTime();
  };
  const upcoming = $derived(host.trips.filter((trip) => when(trip) > now));
  const past = $derived(host.trips.filter((trip) => when(trip) <= now).reverse());
  const next = $derived(upcoming[0] ?? null);
  const later = $derived(upcoming.slice(1));

  /** A trip's risk now, in the chance words, or null: no forecast yet, or the file is old. */
  function riskOf(trip: Trip): { level: 'low' | 'delay' | 'cancel'; cancel: number } | null {
    if (live === null || stale) return null;
    const plan = tripPlan({
      trip: { ...trip, needBy: trip.need_by },
      airports: byCode,
      routes: new Map(),
      live: live.byCode,
      now,
    });
    const leg = plan?.legs[0];
    return leg === undefined ? null : { level: legLevel(leg), cancel: leg.cancel };
  }

  // Google's answer from /google.html, sent once the account is read (trips.ts takeGoogleReturn).
  let returned = $state<ReturnType<typeof takeGoogleReturn>>(null);
  let googleNote = $state<string | null>(null);
  let found = $state<readonly { found: FoundFlight; match: Match; added: string | null }[] | null>(
    null,
  );
  let looking = $state(false);

  onMount(() => {
    try {
      returned = takeGoogleReturn(window.sessionStorage);
    } catch {
      returned = null;
    }
    // A return from Google: its finish is the Google state, never a read sent beside it.
    if (returned !== null) host.holdGoogle();
    host.load();
    // A Gmail demo read a reload cut short: its grant is revoked now.
    void revokeLeftover();
  });

  $effect(() => {
    const answer = returned;
    if (answer === null || host.client === null || host.status !== 'ready') return;
    returned = null;
    const denied = answer.code === null || answer.state === null;
    if (denied) googleNote = tripsCopy.google.denied;
    // A refused connect can also end the link there was (the grant Google revoked): the host
    // reads the state again, never shows connected from before.
    void host.finishGoogle(answer.code, answer.state).then((done) => {
      if (!denied) googleNote = done ? null : tripsCopy.google.failed;
    });
  });

  async function connect(): Promise<void> {
    const client = host.client;
    if (client === null) return;
    try {
      const base = new URL('./', location.href).pathname;
      location.assign(await client.startGoogle(base));
    } catch {
      googleNote = tripsCopy.google.failed;
    }
  }

  async function disconnect(): Promise<void> {
    const client = host.client;
    if (client === null) return;
    try {
      await client.disconnectGoogle();
      host.setGoogle({ configured: true, connected: false });
      found = null;
      googleNote = tripsCopy.google.disconnected;
    } catch {
      googleNote = tripsCopy.google.failed;
    }
  }

  async function matchAll(flights: readonly FoundFlight[]): Promise<void> {
    const rows = await Promise.all(
      flights.map(async (flight) => ({
        found: flight,
        match: matchFound(flight, flight.from === null ? null : await files.routes(flight.from)),
        added: null,
      })),
    );
    found = rows;
  }

  async function fromCalendarEvents(): Promise<void> {
    const client = host.client;
    if (client === null || looking) return;
    looking = true;
    googleNote = null;
    try {
      const events = await client.calendar();
      const flights = events
        .map((event) => fromCalendar(event, byCode))
        .filter((flight): flight is FoundFlight => flight !== null);
      if (flights.length === 0) googleNote = tripsCopy.google.noneFound;
      await matchAll(flights);
    } catch {
      googleNote = tripsCopy.google.calendarFailed;
    } finally {
      looking = false;
    }
  }

  async function fromGmail(): Promise<void> {
    // The demo's own client, never Connect Google's (gmail-read.ts).
    const id = host.google.gmail_client_id;
    if (id === null || looking) return;
    looking = true;
    googleNote = null;
    try {
      const { readGmail } = await import('./gmail-read');
      const flights = await readGmail(id, byCode);
      if (flights.length === 0) googleNote = tripsCopy.google.gmailNone;
      await matchAll(flights);
    } catch {
      googleNote = tripsCopy.google.gmailFailed;
    } finally {
      looking = false;
    }
  }

  async function add(
    index: number,
    trip: Extract<Match, { state: 'matched' }>['trip'],
  ): Promise<void> {
    const saved = await host.save(trip);
    if (saved === null || found === null) return;
    found = found.map((row, i) => (i === index ? { ...row, added: saved.id } : row));
  }
</script>

<PanelShell label={tripsCopy.title} shows="trips" {onclose} {onsettle}>
  {#snippet head()}
    <h2 class="fl-name">{tripsCopy.title}</h2>
  {/snippet}

  {#if host.status === 'none' || host.status === 'signedOut'}
    <p class="fl-text">{tripsCopy.signedOut}</p>
    {#if host.status === 'signedOut'}
      <div class="fl-actions">
        <button
          class="fl-action"
          type="button"
          onclick={() => {
            host.signIn();
          }}
          data-testid="trips-sign-in">{tripsCopy.signIn}</button
        >
      </div>
    {/if}
  {:else if host.status === 'loading'}
    <p class="fl-note">{tripsCopy.loading}</p>
  {:else if host.status === 'failed'}
    <p class="fl-note">{tripsCopy.failed}</p>
  {:else}
    {#if host.note !== null}<p class="fl-small" role="status">{host.note}</p>{/if}
    {#if stale && live !== null}
      <p class="fl-note">{updated((now - live.at) / 60_000, true)}</p>
    {/if}
    {#if next === null}
      <p class="fl-text" data-testid="trips-none">{tripsCopy.none}</p>
    {:else}
      {@const from = byCode.get(next.from)}
      {@const to = byCode.get(next.to)}
      {@const risk = riskOf(next)}
      <section class="fl-block" data-testid="trip-next">
        <p class="fl-kind">{tripsCopy.next}</p>
        <button
          type="button"
          class="fl-trip"
          onclick={() => {
            onopen(next);
          }}
          data-level={risk?.level}
        >
          <span class="fl-kind"
            >{flightName(next.carrier, next.number)}&nbsp;·&nbsp;{tripWhen(
              next.day,
              next.leaves,
            )}</span
          >
          <span class="fl-ends">
            <span class="fl-end">
              <span class="fl-code">{from?.code ?? ''}</span>
              <span class="fl-small">{from?.city ?? ''}</span>
              <span class="fl-time">{clock(next.leaves)}</span>
              {#if from !== undefined}<span class="fl-small"
                  >{zoneName(from.tz, instantOf(next.day, next.leaves, from.tz))}</span
                >{/if}
            </span>
            <span class="fl-line" aria-hidden="true">
              <svg viewBox="0 0 16 16" focusable="false"
                ><path
                  d="M8 1.75v12.5M8 5.5L2.25 9v1.25L8 8.5l5.75 1.75V9zM5.75 14.25L8 13l2.25 1.25"
                /></svg
              >
            </span>
            <span class="fl-end">
              <span class="fl-code">{to?.code ?? ''}</span>
              <span class="fl-small">{to?.city ?? ''}</span>
              <span class="fl-time">{clock(next.lands)}</span>
              {#if to !== undefined}<span class="fl-small"
                  >{zoneName(to.tz, instantOf(next.day, next.lands, to.tz))}</span
                >{/if}
            </span>
          </span>
          <span class="fl-facts">
            <span class="fl-fact">
              <span class="fl-dt">{tripsCopy.rows.risk}</span>
              <span class="fl-dd"
                >{risk === null ? tripsCopy.rows.noForecast : levelWord(risk.level)}</span
              >
            </span>
            {#if risk !== null}
              <span class="fl-fact">
                <span class="fl-dt">{tripsCopy.rows.cancel}</span>
                <span class="fl-dd">{percentName(risk.cancel)}</span>
              </span>
            {/if}
            <span class="fl-fact">
              <span class="fl-dt">{tripsCopy.ticket.label}</span>
              <span class="fl-dd">{ticketName(next.ticket)}</span>
            </span>
          </span>
        </button>
      </section>
    {/if}

    {#if later.length > 0}
      <section class="fl-block" data-testid="trips-later">
        <h3 class="fl-heading">{tripsCopy.later}</h3>
        <div class="fl-rows">
          {#each later as trip (trip.id)}
            {@const risk = riskOf(trip)}
            <button
              type="button"
              class="fl-row-button fl-row-flush"
              onclick={() => {
                onopen(trip);
              }}
              data-level={risk?.level}
            >
              <span class="fl-row-label">
                <span>{tripTitle(trip.carrier, trip.number, trip.from, trip.to)}</span>
                <span class="fl-nowrap">{tripWhen(trip.day, trip.leaves)}</span>
              </span>
              <span class="fl-nowrap"
                >{risk === null ? tripsCopy.rows.noForecast : levelWord(risk.level)}</span
              >
            </button>
          {/each}
        </div>
      </section>
    {/if}

    {#if past.length > 0}
      <section class="fl-block">
        <button
          type="button"
          class="fl-action"
          aria-expanded={showPast}
          onclick={() => (showPast = !showPast)}>{tripsCopy.past}</button
        >
        {#if showPast}
          <div class="fl-rows" data-testid="trips-past">
            {#each past as trip (trip.id)}
              <button
                type="button"
                class="fl-row-button fl-row-flush"
                onclick={() => {
                  onopen(trip);
                }}
              >
                <span class="fl-row-label">
                  <span>{tripTitle(trip.carrier, trip.number, trip.from, trip.to)}</span>
                  <span class="fl-nowrap">{tripWhen(trip.day, trip.leaves)}</span>
                </span>
              </button>
            {/each}
          </div>
        {/if}
      </section>
    {/if}

    {#if host.google.configured}
      <section class="fl-block" data-testid="trips-google">
        <h3 class="fl-heading">{tripsCopy.google.title}</h3>
        {#if host.googleState?.connected === true}
          <p class="fl-small">
            {connectedAs(host.googleState.email ?? '', localDay(host.googleState.since))}
          </p>
          <div class="fl-actions">
            <button class="fl-action" type="button" disabled={looking} onclick={fromCalendarEvents}
              >{tripsCopy.google.calendar}</button
            >
          </div>
        {:else}
          <p class="fl-small">{tripsCopy.google.connectHint}</p>
          <div class="fl-actions">
            <button class="fl-action" type="button" onclick={connect} data-testid="google-connect"
              >{tripsCopy.google.connect}</button
            >
          </div>
        {/if}
        {#if host.google.gmail_demo}
          <div class="fl-actions">
            <button
              class="fl-action"
              type="button"
              disabled={looking}
              onclick={fromGmail}
              data-testid="gmail-find">{tripsCopy.google.gmail}</button
            >
          </div>
          <p class="fl-small">{tripsCopy.google.gmailHint}</p>
        {/if}
        {#if looking}<p class="fl-note">{tripsCopy.google.looking}</p>{/if}
        {#if googleNote !== null}<p class="fl-small" role="status">{googleNote}</p>{/if}
        {#if found !== null && found.length > 0}
          <p class="fl-text fl-found">{tripsCopy.google.found}</p>
          <p class="fl-small">{tripsCopy.google.foundHint}</p>
          <div class="fl-cards" data-testid="google-found">
            {#each found as row, index (index)}
              <div class="fl-card">
                {#if row.match.state === 'matched'}
                  {@const trip = row.match.trip}
                  <p class="fl-text">{foundName(trip.carrier, trip.number, trip.day)}</p>
                  <p class="fl-small">{legName(trip.from, trip.to, trip.leaves)}</p>
                  <p class="fl-small">{ticketLine(trip.ticket)}</p>
                  {#if row.added === null}
                    <div class="fl-chips" role="group" aria-label={tripsCopy.ticket.question}>
                      {#each TICKET_KEYS as key (key)}
                        <button
                          type="button"
                          class="fl-chip"
                          aria-pressed={trip.ticket === key}
                          onclick={() => {
                            if (found === null || row.match.state !== 'matched') return;
                            found = found.map((r, i) =>
                              i === index && r.match.state === 'matched'
                                ? {
                                    ...r,
                                    match: { state: 'matched', trip: { ...trip, ticket: key } },
                                  }
                                : r,
                            );
                          }}>{ticketName(key)}</button
                        >
                      {/each}
                    </div>
                    <div class="fl-actions">
                      <button
                        class="fl-primary"
                        type="button"
                        onclick={() => add(index, trip)}
                        data-testid="found-add">{tripsCopy.google.add}</button
                      >
                    </div>
                  {:else}
                    <p class="fl-small">{tripsCopy.added}</p>
                  {/if}
                {:else if row.match.state === 'pick'}
                  <p class="fl-text">
                    {foundName(row.found.carrier, row.found.number, row.found.day ?? '')}
                  </p>
                  <p class="fl-small">{tripsCopy.google.pick}</p>
                  <div class="fl-chips" role="group" aria-label={tripsCopy.google.pick}>
                    {#each row.match.options as option (option.to)}
                      <button
                        type="button"
                        class="fl-chip"
                        onclick={() => {
                          if (found === null) return;
                          found = found.map((r, i) =>
                            i === index ? { ...r, match: { state: 'matched', trip: option } } : r,
                          );
                        }}>{routeName(option.from, option.to)}</button
                      >
                    {/each}
                  </div>
                {:else}
                  <p class="fl-text">{flightName(row.found.carrier, row.found.number)}</p>
                  <p class="fl-small">{tripsCopy.google.notMatched}</p>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
        {#if host.googleState?.connected === true}
          <div class="fl-actions">
            <button class="fl-action" type="button" onclick={disconnect}
              >{tripsCopy.google.disconnect}</button
            >
          </div>
        {/if}
      </section>
    {/if}
  {/if}
</PanelShell>
