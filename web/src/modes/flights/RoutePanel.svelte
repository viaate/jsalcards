<script lang="ts">
  import { tick, untrack } from 'svelte';
  import {
    BLOCK_KEYS,
    cellFlights,
    cellLabel,
    clock,
    dayName,
    flightName,
    flightsCopy,
    heroNumber,
    hubChance,
    hubLine,
    hubNone,
    lateFact,
    cancelAnswer,
    percent,
    routeName,
    safestChance,
    sameChance,
    passedFact,
    clockAt,
    faaWait,
    faaOldFact,
    bothFact,
    usualSomeFact,
    heldTodayFact,
    cellHeld,
    updated,
    usualAnswer,
    usualFacts,
    usualDaysFact,
    usualNoteFor,
    cellChance,
    liveWait,
  } from '../../copy-flights';
  import type { BlockKey, Fact } from '../../copy-flights';
  import Facts from './Facts.svelte';
  import Hero from './Hero.svelte';
  import PanelShell from '../../ui/PanelShell.svelte';
  import type { FlightsRoutes } from '../../types/generated';
  import { dayHero, dayViews, levelOf, localParts, localToday, pillOf, todayView } from './chance';
  import type { Level } from './chance';
  import { bestTime, faaHolds, holdsOn, routeGrid } from './schedule';
  import type { BestTime, Cell, CellState, Hold, Rated, RouteBack } from './schedule';
  import { faaFacts, faaLive, isStale } from './data';
  import type { Airport, FlightsFiles, LiveRead } from './data';

  interface Props {
    from: Airport | null;
    to: Airport | null;
    day: number;
    byCode: ReadonlyMap<string, Airport>;
    live: LiveRead | null;
    /** Whether the live file could not be read and none is shown: said so, never as reading. */
    failed: boolean;
    files: FlightsFiles;
    now: number;
    /** Coming back from a flight opened from a row: its cell picked, and the row focused. */
    back?: RouteBack | null;
    onclose: () => void;
    onflight: (carrier: string, number: number, day: number, back: RouteBack) => void;
    onsettle: () => void;
  }

  let {
    from,
    to,
    day,
    byCode,
    live,
    failed,
    files,
    now,
    back = null,
    onclose,
    onflight,
    onsettle,
  }: Props = $props();

  let routes = $state<FlightsRoutes | null | undefined>(undefined);
  let picked = $state<{ day: number; block: number } | null>(null);
  /** The hubs a route with no nonstop flights usually connects at (D13), once looked up. */
  let hubs = $state<readonly Airport[] | null>(null);

  /** The row to give the focus back to once its cell's rows are drawn (TRAV-R12-S1). */
  let restore = untrack(() => back);
  let rowsElement = $state<HTMLElement | undefined>(undefined);

  $effect(() => {
    const code = from?.code;
    routes = undefined;
    picked = untrack(() => (restore === null ? null : { day: restore.day, block: restore.block }));
    if (code === undefined) return;
    void files.routes(code).then((read) => {
      if (code === from?.code) routes = read;
    });
  });

  /** The newest posted month's flights on this route, and that month. */
  const usual = $derived.by(() => {
    if (routes === null || routes === undefined || to === null) return null;
    const month = routes.months[0];
    if (month === undefined) return null;
    return {
      month: month.month,
      flights: month.flights.filter((flight) => flight.to_airport === to.code),
    };
  });

  // No nonstop flights: the big airports it usually flies to that usually fly on to `to`.
  $effect(() => {
    const month = routes?.months[0];
    const end = to?.code;
    hubs = null;
    if (month === undefined || end === undefined || usual === null || usual.flights.length > 0)
      return;
    const candidates = [...new Set(month.flights.map((flight) => flight.to_airport))]
      .map((code) => byCode.get(code))
      .filter((airport): airport is Airport => airport !== undefined && airport.code !== end)
      .sort((a, b) => b.perDay - a.perDay)
      .slice(0, 8);
    void Promise.all(candidates.map((hub) => files.routes(hub.code))).then((reads) => {
      if (end !== to?.code) return;
      hubs = candidates
        .filter((_, i) =>
          (reads[i]?.months[0]?.flights ?? []).some((flight) => flight.to_airport === end),
        )
        .slice(0, 4);
    });
  });

  const fromLive = $derived(from === null ? null : (live?.byCode.get(from.code) ?? null));
  const toLive = $derived(to === null ? null : (live?.byCode.get(to.code) ?? null));
  // From the clock, so a file that cannot be read again turns gray as it ages (data.ts isStale).
  const stale = $derived(isStale(live, now));
  /** An old file's age, said on each cell for a screen reader as the grid's gray shows it. */
  const oldWords = $derived(
    stale && live !== null ? updated((now - live.at) / 60_000, true) : null,
  );
  const today = $derived(from === null ? '' : localToday(from.tz, now));

  const grid = $derived(
    usual === null || from === null || to === null || fromLive === null || toLive === null
      ? null
      : routeGrid(
          usual.flights,
          { entry: fromLive, zone: from.tz },
          { entry: toLive, zone: to.tz },
          today,
          now,
        ),
  );
  /** A live FAA hold at either end: the times it may cover are never named the safest (LR-F14.3). */
  const holds = $derived(
    from === null || to === null || stale
      ? []
      : faaHolds(
          live,
          [
            { code: from.code, entry: fromLive },
            { code: to.code, entry: toLive },
          ],
          from.tz,
          now,
        ),
  );
  const answer = $derived<BestTime>(
    grid === null || from === null ? { kind: 'none' } : bestTime(grid, { holds, zone: from.tz }),
  );
  const toTime = (pick: { date: string; block: number }): { day: string; block: BlockKey } => ({
    day: pick.date,
    block: BLOCK_KEYS[pick.block] ?? 'early',
  });

  /**
   * The cell shown: the one picked, else the address's day's first with a value, else the safest.
   * With an old file, only the one picked: no time is named the safest from it.
   */
  const shown = $derived.by(() => {
    if (picked !== null) return picked;
    if (grid === null || stale) return null;
    if (day > 0) {
      const block = grid[day]?.cells.findIndex((cell) => cell.flights.length > 0) ?? -1;
      if (block >= 0) return { day, block };
    }
    // The safest time, or under a tie the earliest no hold covers: the time whose numbers the
    // headline gives, never a held one (TRAV-R11-B2).
    if (answer.kind === 'safest' || answer.kind === 'tie')
      return { day: answer.pick.index, block: answer.pick.block };
    for (const row of grid) {
      const block = row.cells.findIndex((cell) => cell.flights.length > 0);
      if (block >= 0) return { day: row.index, block };
    }
    return null;
  });
  const shownRows = $derived(
    shown === null || grid === null ? [] : (grid[shown.day]?.cells[shown.block]?.flights ?? []),
  );
  // Back from a flight opened from a row: that row takes the focus again once it is drawn, by a
  // keyboard, a tap or a screen reader's tap alike (TRAV-R13-S1). Without a ring after a tap, it
  // looks the same; with the row gone, the panel takes it.
  $effect(() => {
    const element = rowsElement;
    if (restore === null || element === undefined || shownRows.length === 0) return;
    const { row } = restore;
    restore = null;
    void tick().then(() => {
      const target =
        element.querySelectorAll<HTMLElement>('.fl-row-button')[row] ??
        element.closest<HTMLElement>('.detail');
      target?.focus({ preventScroll: true });
    });
  });

  /**
   * Whether a cell's level is more than its cancel chance alone makes, from its chance of a long
   * delay, which the cell does not show: its name says so, and the note under the grid (TRAV-R11-S2).
   */
  function fromLate(best: Rated): boolean {
    const { level } = pillOf(best.chance);
    const { cancel } = best.chance;
    return !stale && level !== null && level !== levelOf(cancel ?? 0, 0);
  }

  /** Whether a grid cell reads "No forecast" (emptyWords): the note under the grid says why. */
  function showsNoForecast(cell: Cell): boolean {
    return (
      (cell.best?.chance.cancel ?? null) === null && cell.state !== 'over' && cell.state !== 'none'
    );
  }

  function emptyWords(state: CellState): string {
    if (state === 'over') return flightsCopy.over;
    if (state === 'none') return flightsCopy.route.none;
    return flightsCopy.noForecast;
  }

  /**
   * The FAA's live programs at either end, each said under the answer (LR-F9, TRAV-R13-S3; LR-F4
   * leaves them out of it), but for those the answer itself names (`named`).
   */
  const faaUnder = (counted: boolean, named: readonly Hold[] = []): Fact[] => {
    if (live === null || stale) return [];
    const at = (code: string): number[] =>
      named.filter((hold) => hold.code === code).map((hold) => hold.program);
    return [
      ...(from === null
        ? []
        : faaFacts(live, fromLive, from.code, from.tz, now, counted, false, at(from.code))),
      ...(to === null
        ? []
        : faaFacts(live, toLive, to.code, to.tz, now, counted, to.tz !== from?.tz, at(to.code))),
    ];
  };
  /**
   * An FAA read 30 minutes old or more, on a file that is not old: its age in gray, as the airport
   * panel gives it (LR-F15.3b), so no FAA line is missed for one that is not current. The pick
   * already leaves it out (faaHolds).
   */
  const faaOld = $derived.by((): Fact[] => {
    const at = live?.file.programs_at ?? null;
    if (live === null || stale || at === null || faaLive(live, now)) return [];
    return [faaOldFact((now - Date.parse(at)) / 60_000)];
  });
  /**
   * A hold's airport's clock time it was set to end at, once that has passed (TRAV-R10-B3), named
   * by that airport where its clock is not the origin's (TRAV-R11-S4).
   */
  const endedAt = (hold: { code: string; ends: number; ended: boolean }): string | null => {
    const zone = hold.code === from?.code ? from.tz : hold.code === to?.code ? to.tz : null;
    if (!hold.ended || zone === null) return null;
    const time = clock(localParts(new Date(hold.ends), zone).minute);
    return zone === from?.tz ? time : clockAt(time, hold.code);
  };
  /** A hold as the lines name it, with its stated end once that has passed. */
  const holdSaid = (hold: Hold): { program: number; code: string; endedAt: string | null } => ({
    program: hold.program,
    code: hold.code,
    endedAt: endedAt(hold),
  });
  /** A grid cell's holds for its name (TRAV-R12-S2): none on an old file, which holds nothing. */
  const cellHolds = (date: string, block: number): string =>
    from === null ? '' : cellHeld(holdsOn(date, block, { holds, zone: from.tz }).map(holdSaid));

  /** Under an answer with no number: the facts alone. */
  const faaNow = $derived(faaUnder(false));
  /** Under the safest time's chance: with the note that the chance does not count them. */
  const faaCounted = $derived(faaUnder(true));

  /** The rows under Best time to fly's answer (LR-F18.2). */
  const heroRows = $derived.by((): Fact[] => {
    // A lone hold the answer names is not said again; several, it leaves each to these rows.
    if (answer.kind === 'faa')
      return [...faaUnder(false, answer.holds.length === 1 ? answer.holds : []), ...faaOld];
    if (answer.kind !== 'safest' && answer.kind !== 'tie') return [...faaNow, ...faaOld];
    // A live FAA program first, right under the headline (LR-F9): the fact that matters most now.
    const lines: Fact[] = [...faaCounted, ...faaOld];
    // Why today is not named, when a hold covers it and the pick is a later day (LR-F15.3a).
    // A hold past its stated end is said as set to end then, never as holding today now.
    if (answer.todayHeld !== null)
      lines.push(heldTodayFact(answer.todayHeld.holds.map(holdSaid), answer.todayHeld.all));
    if (answer.best.chance.late !== null) lines.push(lateFact(answer.best.chance.late));
    // A lower cancel chance passed over for its level: the time and its shown numbers
    // (LR-F16.2, LR-F18.2); the grid's colors show its level.
    if (answer.kind === 'safest' && answer.passed !== null)
      lines.push(
        passedFact(answer.passed.date, today, BLOCK_KEYS[answer.passed.block] ?? 'early', {
          cancel: answer.passed.best.chance.cancel ?? 0,
          late: answer.passed.best.chance.late,
        }),
      );
    lines.push(bothFact());
    if (answer.usualDays.length > 0) lines.push(usualDaysFact(answer.usualDays, today));
    else if (answer.usualSome) lines.push(usualSomeFact());
    return lines;
  });

  /**
   * The airports a usual cancel value in the grid comes from, for the usual mark's note: the grid
   * shows the cancel number alone, and marks it by its own values (LR-SF8).
   */
  const usualEnds = $derived.by(() => {
    if (grid === null || from === null || to === null) return [];
    const chances = grid.flatMap((row) => row.cells.map((cell) => cell.best?.chance ?? null));
    return [
      ...(chances.some((chance) => chance?.fromCancelUsual === true) ? [from.code] : []),
      ...(chances.some((chance) => chance?.toCancelUsual === true) ? [to.code] : []),
    ];
  });

  /** A hub's chance of a cancel today, at its own clock, with its number. */
  function hubAnswer(hub: Airport): { text: string; level: Level | undefined } {
    const entry = live?.byCode.get(hub.code);
    if (entry === undefined || stale) return { text: hubNone(), level: undefined };
    const view = todayView(dayViews(entry, hub.tz, now), hub.tz, now);
    const hero = view === null ? null : dayHero(view, null);
    if (view === null || hero === null) return { text: hubNone(), level: undefined };
    return {
      // The cancel number's own flags (LR-SF1): a usual cancel chance is said so.
      // With no counts the chance is one time's, the riskiest left: named, never said as the day's.
      text: hubChance(
        hero.cancel,
        hero.cancelUsual,
        hero.block === null ? null : (BLOCK_KEYS[hero.block] ?? null),
      ),
      // A usual number never takes a forecast level color (LR-SF8).
      level: hero.usual === 'none' ? (view.level ?? undefined) : undefined,
    };
  }
</script>

<PanelShell
  label={from !== null && to !== null ? routeName(from.code, to.code) : flightsCopy.route.title}
  shows={`route:${from?.code ?? ''}-${to?.code ?? ''}`}
  {onclose}
  {onsettle}
>
  {#snippet head()}
    <p class="fl-kind">{flightsCopy.route.title}</p>
    <h2 class="fl-name">
      {#if from !== null && to !== null}{routeName(from.code, to.code)}{/if}
    </h2>
    {#if from !== null && to !== null}
      <p class="fl-place">{routeName(from.city, to.city)}</p>
    {/if}
  {/snippet}

  {#if live === null}
    <p class="fl-note">{liveWait(failed)}</p>
  {:else if routes === undefined}
    <p class="fl-note">{flightsCopy.live.loading}</p>
  {:else if routes === null}
    <p class="fl-note">{flightsCopy.route.notReady}</p>
  {:else if usual === null || usual.flights.length === 0}
    <!-- No nonstop flights: the hubs it usually connects at, each with its chance today (D13). -->
    <section class="fl-block" data-testid="flights-hubs">
      <p class="fl-text">{flightsCopy.route.hubs}</p>
      {#if hubs === null}
        <p class="fl-note">{flightsCopy.live.loading}</p>
      {:else if hubs.length === 0}
        <p class="fl-note">{flightsCopy.route.hubsNone}</p>
      {:else}
        <ul class="fl-list">
          {#each hubs as hub (hub.code)}
            {@const said = hubAnswer(hub)}
            <li class="fl-text">
              {hubLine(hub.code, hub.city, said.text)}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {:else if grid === null}
    <p class="fl-note">{flightsCopy.live.notRead}</p>
  {:else}
    {#if stale && live !== null}
      <Hero
        number={null}
        meaning={updated((now - live.at) / 60_000, true)}
        old
        testid="flights-best"
      />
    {:else if answer.kind === 'safest'}
      <Hero
        number={heroNumber(answer.best.chance.cancel ?? 0)}
        meaning={safestChance(
          toTime(answer.pick),
          today,
          answer.usualDays.length > 0 || answer.usualSome,
        )}
        rows={heroRows}
        testid="flights-best"
      />
    {:else if answer.kind === 'tie'}
      <Hero
        number={null}
        meaning={sameChance(
          answer.best.chance.cancel ?? 0,
          answer.usualDays.length > 0 || answer.usualSome,
          answer.held,
          answer.heldBy.every((hold) => hold.ended) ? answer.heldBy : [],
        )}
        rows={heroRows}
        testid="flights-best"
      />
    {:else if answer.kind === 'faa'}
      <Hero
        number={null}
        meaning={faaWait(answer.holds.map(holdSaid))}
        rows={heroRows}
        testid="flights-best"
      />
    {:else if answer.kind === 'usual'}
      <Hero
        number={null}
        meaning={flightsCopy.route.allUsual}
        rows={[
          ...faaNow,
          ...faaOld,
          ...usualFacts({ cancel: answer.cancelShare, late: answer.lateShare, run: true }),
        ]}
        testid="flights-best"
      />
    {:else}
      <Hero
        number={null}
        meaning={flightsCopy.route.noForecast}
        rows={[...faaNow, ...faaOld]}
        testid="flights-best"
      />
    {/if}

    <!-- Three days by five blocks, the safest flight of each block in its color. -->
    <div class="fl-grid" class:is-old={stale} data-testid="flights-grid">
      <span></span>
      {#each BLOCK_KEYS as key (key)}<span class="fl-col">{flightsCopy.blocks[key]}</span>{/each}
      {#each grid as dayRow (dayRow.index)}
        {@const name = dayName(dayRow.date, today, stale)}
        <span class="fl-day">{name}</span>
        {#each dayRow.cells as cell, block (block)}
          {@const blockKey = BLOCK_KEYS[block] ?? 'early'}
          {@const best = cell.best}
          {@const value = best === null ? null : best.chance.cancel}
          {#if best === null || value === null}
            <span
              class="fl-cell is-none"
              role="img"
              aria-label={cellLabel(name, blockKey, emptyWords(cell.state), oldWords)}
              >{cell.state === 'none' ? flightsCopy.route.noneShort : emptyWords(cell.state)}</span
            >
          {:else}
            <button
              type="button"
              class="fl-cell"
              class:is-usual={pillOf(best.chance).usual !== 'none'}
              data-level={stale ? undefined : (pillOf(best.chance).level ?? undefined)}
              aria-pressed={shown?.day === dayRow.index && shown.block === block}
              aria-label={cellLabel(
                name,
                blockKey,
                cellChance(
                  value,
                  pillOf(best.chance).usual,
                  stale ? null : pillOf(best.chance).level,
                  fromLate(best),
                ) + cellHolds(dayRow.date, block),
                oldWords,
              )}
              onclick={() => (picked = { day: dayRow.index, block })}>{percent(value)}</button
            >
          {/if}
        {/each}
      {/each}
    </div>

    {#if shown !== null}
      <section class="fl-block">
        <h3 class="fl-heading">
          {cellFlights(
            grid[shown.day]?.date ?? today,
            today,
            BLOCK_KEYS[shown.block] ?? 'early',
            usual.month,
          )}
        </h3>
        {#if (grid[shown.day]?.date ?? today) === today}
          <!-- Today's flights: a live FAA program at either end, said by the rows it touches. -->
          <Facts rows={faaNow} />
        {/if}
        <div class="fl-rows" bind:this={rowsElement}>
          {#each shownRows as rated, i (i)}
            <button
              type="button"
              class="fl-row-button"
              onclick={() => {
                // One that leaves after midnight in a night cell leaves the day after its row's.
                onflight(
                  rated.flight.carrier,
                  rated.flight.number,
                  shown.day + (rated.day === grid[shown.day]?.date ? 0 : 1),
                  { day: shown.day, block: shown.block, row: i },
                );
              }}
            >
              <span
                >{flightName(rated.flight.carrier, rated.flight.number)}&nbsp;·&nbsp;{clock(
                  rated.flight.leaves,
                )}</span
              >
              {#if rated.chance.cancel !== null && stale}
                <!-- An old file: its number only, gray, never a level said as current. -->
                <span class="fl-pill is-old">{cancelAnswer(rated.chance.cancel)}</span>
              {:else if rated.chance.cancel !== null}
                <!-- Its number, in its level's color: never a level said as a sentence (LR-F9). A
                     cancel chance that is the usual rate in whole or in part is said so, by its own
                     two values, with no level color (LR-SF8). -->
                {@const pill = pillOf(rated.chance)}
                <span class="fl-pill" data-level={stale ? undefined : (pill.level ?? undefined)}
                  >{pill.usual === 'none'
                    ? cancelAnswer(rated.chance.cancel)
                    : usualAnswer(rated.chance.cancel, pill.usual === 'part')}</span
                >
              {:else}
                <span class="fl-pill">{flightsCopy.noForecast}</span>
              {/if}
            </button>
          {/each}
        </div>
      </section>
    {/if}
    {#if grid.some( (d) => d.cells.some((cell) => cell.best !== null && pillOf(cell.best.chance).usual !== 'none') )}
      <p class="fl-note">{usualNoteFor(usualEnds)}</p>
    {/if}
    {#if grid.some((d) => d.cells.some(showsNoForecast))}
      <p class="fl-note" data-testid="flights-no-forecast-note">
        {flightsCopy.route.noForecastNote}
      </p>
    {/if}
    {#if grid.some((d) => d.cells.some((cell) => cell.best !== null && fromLate(cell.best)))}
      <p class="fl-note" data-testid="flights-late-note">{flightsCopy.route.lateNote}</p>
    {/if}
  {/if}
</PanelShell>
