<!--
  Backup plans (flights spec D18, D21 pattern 8): when a trip looks risky, the other ways to get
  there as compact rows in backup.ts rankPlans order (the safer ones first, the same airline
  first): the flight and its time, what kind of plan it is, its rough chance with a bar, and the
  airline's travel alerts link to switch there (never a booking). Then the advice for the ticket
  type with the waiver state (D19, W8), the money words and plain rules, every time. Worked in
  the browser from the published files (backup.ts).
-->
<script lang="ts">
  import { untrack } from 'svelte';

  import { airlineName, flightName, flightsCopy } from '../../copy-flights';
  import {
    arriveWords,
    backupName,
    nearbyWords,
    switchLink,
    tripsCopy,
    viaName,
    type TicketKey,
  } from '../../copy-trips';
  import type { FlightsRoutes } from '../../types/generated';
  import {
    MAX_PLANS,
    airportsNeeded,
    backupPlans,
    legLevel,
    looksRisky,
    tripPlan,
    type Plan,
    type TripLike,
  } from './backup';
  import type { Level } from './chance';
  import { AIRLINE_SITES, waiverState } from './data';
  import type { Airport, FlightsFiles, LiveRead, WaiversRead } from './data';
  import { adviceFor } from './ticket';

  interface Props {
    trip: TripLike;
    ticket: TicketKey;
    byCode: ReadonlyMap<string, Airport>;
    live: LiveRead;
    waivers: WaiversRead | null;
    files: FlightsFiles;
    now: number;
  }

  let { trip, ticket, byCode, live, waivers, files, now }: Props = $props();

  let routes = $state<ReadonlyMap<string, FlightsRoutes | null> | null>(null);

  // The usual flights the plans need: the trip's airport first (its hubs come from it), then the
  // airports nearby and the hubs. Read again only when the route changes, never on a clock tick.
  const ends = $derived(`${trip.from}-${trip.to}`);
  $effect(() => {
    const [from = '', to = ''] = ends.split('-');
    const airports = untrack(() => byCode);
    const stop = new AbortController();
    routes = null;
    void (async () => {
      const first = await files.routes(from);
      // A plain map, handed over whole once read: nothing reads it while it fills.
      // eslint-disable-next-line svelte/prefer-svelte-reactivity
      const kept = new Map<string, FlightsRoutes | null>([[from, first]]);
      const codes = airportsNeeded({ trip: { from, to }, airports, routes: kept }).filter(
        (code) => !kept.has(code),
      );
      const reads = await Promise.all(codes.map((code) => files.routes(code)));
      codes.forEach((code, i) => kept.set(code, reads[i] ?? null));
      if (!stop.signal.aborted) routes = kept;
    })();
    return () => {
      stop.abort();
    };
  });

  const inputs = $derived(
    routes === null ? null : { trip, airports: byCode, routes, live: live.byCode, now },
  );
  const own = $derived(inputs === null ? null : tripPlan(inputs));
  const plans = $derived(inputs === null ? [] : backupPlans(inputs).slice(0, MAX_PLANS));
  const risky = $derived(looksRisky(own));
  const advice = $derived(
    adviceFor(
      ticket,
      [trip.from, trip.to].map((code) =>
        waiverState(waivers, trip.carrier, airlineName(trip.carrier), code, trip.day, now),
      ),
    ),
  );

  function nameOf(plan: Plan): string {
    const [first, second] = plan.legs;
    if (first === undefined) return '';
    const day = plan.dayBefore ? first.day : undefined;
    const name = backupName(first.carrier, first.number, first.leaves, day);
    return second === undefined
      ? name
      : viaName(name, flightName(second.carrier, second.number), first.to);
  }

  function kindOf(plan: Plan): string {
    const first = plan.legs[0];
    if (plan.kind === 'nearby' && first !== undefined) {
      const code = first.from !== trip.from ? first.from : first.to;
      return nearbyWords(code, plan.miles ?? 0);
    }
    if (plan.dayBefore) return tripsCopy.backup.dayBefore;
    return tripsCopy.backup[plan.kind];
  }

  function linkOf(carrier: string): string | null {
    const site = AIRLINE_SITES[carrier];
    if (site === undefined) return null;
    return new URL(waivers?.airlines.get(carrier)?.path ?? '/', site).href;
  }

  /** A plan's color: its riskiest leg's level, from the shown percents (chance.ts levelOf). */
  function worst(plan: Plan): Level {
    const levels = plan.legs.map(legLevel);
    return levels.includes('cancel') ? 'cancel' : levels.includes('delay') ? 'delay' : 'low';
  }
</script>

<section class="fl-block" data-testid="backup-plans">
  <h3 class="fl-heading">{tripsCopy.backup.title}</h3>
  {#if routes === null}
    <p class="fl-note">{flightsCopy.live.loading}</p>
  {:else if own === null}
    <p class="fl-note">{tripsCopy.backup.noForecast}</p>
  {:else if !risky}
    <p class="fl-note" data-testid="backup-fine">{tripsCopy.backup.notRisky}</p>
  {:else}
    <p class="fl-small">{tripsCopy.backup.hint}</p>
    <dl class="fl-plans">
      {#each own.legs.slice(0, 1) as mine (mine.number)}
        <div class="fl-plan is-own" data-level={worst(own)}>
          <dt>
            <span>{backupName(mine.carrier, mine.number, mine.leaves)}</span>
            <span>{tripsCopy.backup.yours}</span>
          </dt>
          <dd>
            <span class="fl-bar" aria-hidden="true"
              ><span style:width={`${String(own.chance)}%`}></span></span
            >
            <span>{arriveWords(own.chance)}</span>
          </dd>
        </div>
      {/each}
      {#each plans as plan (nameOf(plan))}
        {@const first = plan.legs[0]}
        <div class="fl-plan" data-level={worst(plan)} data-testid="backup-plan">
          <dt>
            <span>{nameOf(plan)}</span>
            <span>{kindOf(plan)}</span>
            {#if first !== undefined && linkOf(first.carrier) !== null}
              <a class="fl-link" href={linkOf(first.carrier)} rel="noopener" target="_blank"
                >{switchLink(first.carrier)}</a
              >
            {/if}
          </dt>
          <dd>
            <span class="fl-bar" aria-hidden="true"
              ><span style:width={`${String(plan.chance)}%`}></span></span
            >
            <span>{arriveWords(plan.chance)}</span>
          </dd>
        </div>
      {/each}
    </dl>
    {#if plans.length === 0}<p class="fl-note">{tripsCopy.backup.none}</p>{/if}
  {/if}

  <div class="fl-cards" data-testid="backup-advice">
    <div class="fl-card">
      <p class="fl-card-title">{tripsCopy.backup.how}</p>
      {#each advice.lines as line (line)}
        <p class="fl-small">{line}</p>
      {/each}
      {#if advice.mustGo}<p class="fl-small">{tripsCopy.backup.mustGo}</p>{/if}
    </div>
    <div class="fl-card" data-testid="backup-money">
      <p class="fl-small">{tripsCopy.backup.money}</p>
      <ul class="fl-rules">
        {#each tripsCopy.backup.rules as rule (rule)}
          <li class="fl-small">{rule}</li>
        {/each}
      </ul>
    </div>
  </div>
</section>
