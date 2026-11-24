<!--
  Save a flight to My trips, and the trip's own choices (flights spec D12, D19): Save (signed out,
  it opens the sign-in), the leg pick when the number makes more than one stop that day, the one
  tap on the ticket type, shown once after saving (Skip is Not sure), the ticket type as a chip row
  to change later, "I need to be there by", and Remove. Its buttons are Schools' pin and share
  actions (DetailPanel.svelte .action): words with their marks, no boxes.
-->
<script lang="ts">
  import { TICKET_KEYS, legName, ticketName, tripsCopy, type TicketKey } from '../../copy-trips';
  import type { TripsHost } from './trips-host.svelte';
  import type { Trip } from './trips';

  interface Leg {
    readonly to: string;
    readonly leaves: number;
    readonly lands: number;
  }

  interface Props {
    host: TripsHost;
    carrier: string;
    number: number;
    from: string;
    /** The flight's local day at `from`. */
    day: string;
    /** The leg shown, and every leg the number flies from `from` that day. */
    leg: Leg;
    legs: readonly Leg[];
    /** The arrival airport's local date, for "I need to be there by". */
    arriveDay: string;
  }

  let { host, carrier, number, from, day, leg, legs, arriveDay }: Props = $props();

  const trip = $derived<Trip | null>(host.find(carrier, number, from, day));
  /** The leg pick, open after Save when the number makes more than one stop (D19). */
  let picking = $state(false);
  /** The one tap, open right after a save until it is answered or skipped. */
  let asking = $state<string | null>(null);
  let busy = $state(false);

  async function save(chosen: Leg): Promise<void> {
    if (busy) return;
    busy = true;
    picking = false;
    const saved = await host.save({
      carrier,
      number,
      from,
      to: chosen.to,
      day,
      leaves: chosen.leaves,
      lands: chosen.lands,
    });
    busy = false;
    if (saved !== null && !saved.ticket_asked) asking = saved.id;
  }

  function onSave(): void {
    if (host.status === 'signedOut') {
      host.signIn();
      return;
    }
    if (legs.length > 1) picking = true;
    else void save(leg);
  }

  async function answer(id: string, ticket: TicketKey | null): Promise<void> {
    asking = null;
    await host.change(id, ticket === null ? { ticket_asked: true } : { ticket });
  }

  /** The need-by time as "HH:MM", from the trip's stored local date and time. */
  const needTime = $derived(trip?.need_by?.slice(11, 16) ?? '');
</script>

{#if host.status !== 'none'}
  <section class="fl-block" data-testid="trip-tools">
    <div class="fl-actions">
      {#if trip === null}
        <button
          class="fl-action"
          type="button"
          disabled={busy || host.status === 'loading'}
          onclick={onSave}
          data-testid="trip-save"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M5.75 2.25h4.5l-.6 4.1 2.1 2.15v1.25h-7.5V8.5l2.1-2.15z" />
            <path d="M8 9.75v4" />
          </svg>
          {tripsCopy.save}
        </button>
      {:else}
        <span class="fl-action is-on" data-testid="trip-saved">
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M5.75 2.25h4.5l-.6 4.1 2.1 2.15v1.25h-7.5V8.5l2.1-2.15z" />
            <path d="M8 9.75v4" />
          </svg>
          {tripsCopy.saved}
        </span>
        <button
          class="fl-action"
          type="button"
          onclick={() => {
            void host.remove(trip.id);
          }}
          data-testid="trip-remove">{tripsCopy.remove}</button
        >
      {/if}
    </div>
    {#if host.note !== null}
      <p class="fl-small" role="status">{host.note}</p>
    {/if}

    {#if picking}
      <p class="fl-text">{tripsCopy.legPick}</p>
      <div class="fl-chips" role="group" aria-label={tripsCopy.legPick} data-testid="trip-legs">
        {#each legs as option (option.to)}
          <button
            type="button"
            class="fl-chip"
            onclick={() => {
              void save(option);
            }}>{legName(from, option.to, option.leaves)}</button
          >
        {/each}
      </div>
    {/if}

    {#if trip !== null && asking === trip.id}
      <!-- The one tap (D19), once: four answers and Skip. -->
      <div class="fl-ask" data-testid="ticket-tap">
        <p class="fl-heading">{tripsCopy.ticket.question}</p>
        <p class="fl-small">{tripsCopy.ticket.hint}</p>
        <div class="fl-chips" role="group" aria-label={tripsCopy.ticket.question}>
          {#each TICKET_KEYS as key (key)}
            <button
              type="button"
              class="fl-chip"
              onclick={() => {
                void answer(trip.id, key);
              }}>{ticketName(key)}</button
            >
          {/each}
          <button
            type="button"
            class="fl-chip"
            onclick={() => {
              void answer(trip.id, null);
            }}>{tripsCopy.ticket.skip}</button
          >
        </div>
      </div>
    {:else if trip !== null}
      <dl class="fl-facts">
        <div class="fl-fact">
          <dt>{tripsCopy.ticket.label}</dt>
          <dd>{ticketName(trip.ticket)}</dd>
        </div>
      </dl>
      <div
        class="fl-chips"
        role="group"
        aria-label={tripsCopy.ticket.label}
        data-testid="ticket-row"
      >
        {#each TICKET_KEYS as key (key)}
          <button
            type="button"
            class="fl-chip"
            aria-pressed={trip.ticket === key}
            onclick={() => {
              void host.change(trip.id, { ticket: key });
            }}>{ticketName(key)}</button
          >
        {/each}
      </div>
      <label class="fl-need">
        <span class="fl-small">{tripsCopy.needBy.label}</span>
        <input
          type="time"
          step="900"
          value={needTime}
          onchange={(event) => {
            const value = event.currentTarget.value;
            void host.change(trip.id, {
              need_by: /^\d{2}:\d{2}$/.test(value) ? `${arriveDay}T${value}` : null,
            });
          }}
        />
      </label>
    {/if}
  </section>
{/if}
