<script lang="ts">
  import {
    BLOCK_KEYS,
    airlineName,
    alertName,
    blockChance,
    blockLine,
    dayChance,
    dayName,
    faaAge,
    flightsCopy,
    heroNumber,
    lateFact,
    usualFacts,
    whyFact,
    percent,
    programLine,
    programName,
    programWhy,
    reasonName,
    regionalLine,
    roughLine,
    shortDate,
    updated,
    usualChance,
    valueWords,
    faaDayNote,
    liveWait,
    waiverFound,
    waiverNoneMany,
    waiverNotCheckedMany,
    waiverUnclear,
    regionalNames,
  } from '../../copy-flights';
  import PanelShell from '../../ui/PanelShell.svelte';
  import type { FlightsRoutes } from '../../types/generated';
  import Hero from './Hero.svelte';
  import type { Fact } from '../../copy-flights';
  import RecordBox from './RecordBox.svelte';
  import { blockCounts, dayHero, dayViews, levelOf, localToday } from './chance';
  import type { BlockValue, Level } from './chance';
  import {
    REGIONAL_AIRLINES,
    airportWaivers,
    faaFacts,
    faaLive,
    isStale,
    programsBySeverity,
    faaPrograms,
    programEndClock,
    programEnded,
  } from './data';
  import type { Airport, FlightsFiles, LiveRead, WaiversRead } from './data';

  interface Props {
    code: string;
    airport: Airport | null;
    live: LiveRead | null;
    /** Whether the live file could not be read and none is shown: said so, never as reading. */
    failed: boolean;
    waivers: WaiversRead | null;
    files: FlightsFiles;
    now: number;
    onclose: () => void;
    onsettle: () => void;
  }

  let { code, airport, live, failed, waivers, files, now, onclose, onsettle }: Props = $props();

  /** The day picked; null for the first day with a block left. */
  let picked = $state<number | null>(null);
  let routes = $state<FlightsRoutes | null | undefined>(undefined);

  const zone = $derived(airport?.tz ?? null);
  const entry = $derived(zone === null ? null : (live?.byCode.get(code) ?? null));
  const days = $derived(entry === null || zone === null ? [] : dayViews(entry, zone, now));
  const today = $derived(zone === null ? '' : localToday(zone, now));
  // From the clock, so a file that cannot be read again turns gray as it ages (data.ts isStale).
  const stale = $derived(isStale(live, now));
  const firstLeft = $derived(
    Math.max(
      0,
      days.findIndex((day) => day.blocks.some((block) => !block.over)),
    ),
  );
  const dayIndex = $derived(picked ?? firstLeft);
  const shownDay = $derived(days[dayIndex] ?? null);
  const faaShown = $derived(live !== null && entry !== null && faaLive(live, now));
  /** The line under the FAA card on a day after today: "now" only while the read is live. */
  const dayNote = $derived(
    shownDay === null || shownDay.day === today
      ? null
      : faaDayNote(
          (entry?.programs ?? null) === null || (live?.file.programs_at ?? null) === null
            ? 'none'
            : faaShown
              ? 'live'
              : 'old',
          'airport',
        ),
  );
  const ageMinutes = $derived(live === null ? 0 : (now - live.at) / 60_000);
  const faaMinutes = $derived(
    (live?.file.programs_at ?? null) === null
      ? 0
      : (now - Date.parse(live?.file.programs_at ?? '')) / 60_000,
  );
  /** Whether the forecast, the FAA or an alert says there is weather: a usual rate is told so. */
  const weather = $derived(
    entry !== null &&
      ((entry.why[dayIndex] ?? []).length > 0 ||
        (faaShown && (entry.programs?.length ?? 0) > 0) ||
        (!stale && (entry.alerts?.length ?? 0) > 0)),
  );
  const whys = $derived(entry?.why[dayIndex] ?? []);
  /** The usual flights still to leave in each block of the day shown: the day number's weights. */
  const counts = $derived(
    shownDay === null || zone === null || routes === undefined || routes === null
      ? null
      : blockCounts(routes.months[0]?.flights ?? [], shownDay.day, zone, now),
  );
  /** The answer's number, once the routes are read (undefined before), or null with no value left. */
  const hero = $derived(
    shownDay === null || routes === undefined ? undefined : dayHero(shownDay, counts),
  );
  const heroMeaning = $derived.by(() => {
    if (hero === undefined || hero === null || shownDay === null) return '';
    const block = hero.block === null ? null : (BLOCK_KEYS[hero.block] ?? null);
    if (hero.usual === 'all') return usualChance(shownDay.day, block);
    if (block === null) return dayChance(shownDay.day, today, hero.rest);
    return blockChance(shownDay.day, today, block);
  });
  /** The FAA's live program here, said under the answer as now's (LR-F9), never counted in it. */
  const faaNow = $derived(
    live === null || stale || shownDay?.day !== today
      ? []
      : faaFacts(live, entry, null, zone ?? 'UTC', now),
  );
  /** The same, under an answer with a chance: with the note that the chance does not count it. */
  const faaCounted = $derived(
    live === null || stale || shownDay?.day !== today
      ? []
      : faaFacts(live, entry, null, zone ?? 'UTC', now, true),
  );
  /** The rows under the answer (LR-F18.2): the forecast's reason, then the FAA, then the rest. */
  const heroRows = $derived.by((): Fact[] => {
    if (hero === undefined || hero === null) return faaNow;
    const why = hero.usual === 'all' || whys[0] === undefined ? null : reasonName(whys[0]);
    // A live FAA program first, right under the headline (LR-F9), after the answer's one reason.
    const lines: Fact[] = [...(why === null ? [] : [whyFact(why)]), ...faaCounted];
    if (hero.late !== null) lines.push(lateFact(hero.late));
    if (hero.usual !== 'none') lines.push(...usualFacts(hero.usual === 'all', weather));
    return lines;
  });
  const rough = $derived(entry?.rough[dayIndex] ?? null);
  const roughUsual = $derived(entry !== null && (entry.rough_usual & (1 << dayIndex)) !== 0);
  /**
   * The rough day line: a usual rough day chance is left out beside the day's forecast chances,
   * which already say how rough the day looks; it shows only where the day is all usual.
   */
  const roughShown = $derived(
    !stale && rough !== null && (!roughUsual || hero === null || hero?.usual === 'all'),
  );

  $effect(() => {
    const asked = code;
    routes = undefined;
    picked = null;
    void files.routes(asked).then((read) => {
      if (asked === code) routes = read;
    });
  });

  /** The airlines that usually fly from here, the busiest first; null before the routes are read. */
  const flying = $derived.by(() => {
    const month = routes?.months[0];
    if (month === undefined) return null;
    const counts: Record<string, number> = {};
    for (const flight of month.flights) counts[flight.carrier] = (counts[flight.carrier] ?? 0) + 1;
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([airline]) => airline);
  });
  /**
   * The airlines whose waivers are told (W8): each that usually flies from here, an airline the
   * waivers file does not list named as not checked, never left out; the waivers file's own list
   * before the routes are read. Regional airlines fly under a bigger one's name (W4), which the
   * files do not carry, so they get a line of their own.
   */
  const airlines = $derived(
    waivers === null
      ? []
      : flying === null
        ? [...waivers.airlines.keys()]
        : flying.filter((airline) => !REGIONAL_AIRLINES.has(airline)),
  );
  const regionals = $derived(
    regionalNames((flying ?? []).filter((airline) => REGIONAL_AIRLINES.has(airline))),
  );
  const waiverLines = $derived(
    shownDay === null
      ? null
      : airportWaivers(waivers, airlines, airlineName, code, shownDay.day, now),
  );

  /** A value's words, with the level its bar's color shows where it has one (LR-F15.2). */
  function cellWords(
    value: number | null,
    usual: boolean,
    over: boolean,
    level: (v: number) => Level,
  ): string {
    if (over) return flightsCopy.over;
    if (value === null) return flightsCopy.noForecast;
    return valueWords(value, usual, stale || usual ? null : level(value));
  }

  function rowLabel(block: BlockValue, key: (typeof BLOCK_KEYS)[number]): string {
    return blockLine(
      key,
      cellWords(block.cancel, block.cancelUsual, block.over, levelOfCancel),
      cellWords(block.late, block.lateUsual, block.over, (late) => levelOf(0, late)),
    );
  }

  /** A block's color by its cancel chance alone, from the whole percent it shows (LR-F15.1). */
  function levelOfCancel(cancel: number): 'low' | 'delay' | 'cancel' {
    return levelOf(cancel, 0);
  }
</script>

<PanelShell label={airport?.name ?? code} shows={`airport:${code}`} {onclose} {onsettle}>
  {#snippet head()}
    <p class="fl-kind">
      {code}{#if airport !== null}&nbsp;·&nbsp;{airport.city}, {airport.state}{/if}
    </p>
    <h2 class="fl-name">{airport?.name ?? code}</h2>
  {/snippet}

  {#if live === null}
    <p class="fl-note">{liveWait(failed)}</p>
  {:else if entry === null || shownDay === null}
    <p class="fl-note">{flightsCopy.live.notRead}</p>
  {:else}
    <!--
      The answer first, as Schools' chance: the day's number, true for its line (LR-F9); the usual
      rate said as the usual rate; an old file's age and no number at all.
    -->
    {#if stale}
      <Hero number={null} meaning={updated(ageMinutes, true)} old testid="flights-answer" />
    {:else if hero === undefined}
      <Hero number={null} meaning={flightsCopy.live.loading} testid="flights-answer" />
    {:else if hero === null}
      <Hero
        number={null}
        meaning={shownDay !== null && shownDay.day > today
          ? flightsCopy.noForecastDay
          : flightsCopy.noValueLeft}
        rows={heroRows}
        testid="flights-answer"
      />
    {:else}
      <Hero
        number={heroNumber(hero.cancel)}
        meaning={heroMeaning}
        rows={heroRows}
        testid="flights-answer"
      />
    {/if}

    <div class="fl-chips" role="group" aria-label={flightsCopy.dayGroup}>
      {#each days as day (day.index)}
        <button
          type="button"
          class="fl-chip"
          aria-pressed={day.index === dayIndex}
          onclick={() => (picked = day.index)}>{dayName(day.day, today, stale)}</button
        >
      {/each}
    </div>

    <!-- The day by time of day: a departure's chance of a cancel and of leaving 45+ min late. -->
    <ul class="sr-only" aria-label={shortDate(shownDay.day)}>
      {#each shownDay.blocks as block, i (i)}
        <li>{rowLabel(block, BLOCK_KEYS[i] ?? 'early')}</li>
      {/each}
    </ul>
    <div class="fl-blocks" class:is-old={stale} data-testid="flights-blocks" aria-hidden="true">
      <span class="fl-small">{shortDate(shownDay.day)}</span>
      <span class="fl-col">{flightsCopy.cancel}</span>
      <span class="fl-col">{flightsCopy.late}</span>
      {#each shownDay.blocks as block, i (i)}
        {@const key = BLOCK_KEYS[i] ?? 'early'}
        <span class="fl-when"
          ><span>{flightsCopy.blocks[key]}</span><span>{flightsCopy.blockHours[key]}</span></span
        >
        {#if block.over || block.cancel === null}
          <span class="fl-value is-none"
            >{block.over ? flightsCopy.over : flightsCopy.noForecast}</span
          >
        {:else}
          <span
            class="fl-value"
            data-level={stale || block.cancelUsual ? undefined : levelOfCancel(block.cancel)}
          >
            {percent(block.cancel)}
            {#if block.cancelUsual}<span class="fl-usual">{flightsCopy.usualMark}</span>{/if}
            <span class="fl-bar"
              ><span style:width="{Math.min(100, block.cancel / 3)}%"></span></span
            >
          </span>
        {/if}
        {#if block.over || block.late === null}
          <span class="fl-value is-none"
            >{block.over ? flightsCopy.over : flightsCopy.noForecast}</span
          >
        {:else}
          <span
            class="fl-value"
            data-level={stale || block.lateUsual ? undefined : levelOf(0, block.late)}
          >
            {percent(block.late)}
            {#if block.lateUsual}<span class="fl-usual">{flightsCopy.usualMark}</span>{/if}
            <span class="fl-bar"><span style:width="{Math.min(100, block.late / 5)}%"></span></span>
          </span>
        {/if}
      {/each}
    </div>
    {#if shownDay.blocks.some((block) => !block.over && block.usual)}
      <p class="fl-note fl-usual-note">{flightsCopy.usualNote}</p>
    {/if}
    {#if roughShown && rough !== null}
      <p class="fl-note fl-usual-note">{roughLine(rough, roughUsual)} {flightsCopy.roughNote}</p>
    {/if}

    <section class="fl-block" aria-label={flightsCopy.why.title}>
      <h3 class="fl-heading">{flightsCopy.why.title}</h3>
      {#if stale}
        <!-- An old file's reasons are its own, never now's: in gray, with its age. -->
        {#each whys as why, i (i)}<p class="fl-note">{reasonName(why)}</p>{/each}
        <p class="fl-note" data-testid="flights-why-old">{updated(ageMinutes, true)}</p>
      {:else if whys.length === 0}
        <p class="fl-text">{flightsCopy.why.calm}</p>
      {:else}
        <ul class="fl-list">
          {#each whys as why, i (i)}
            <li class="fl-text">{reasonName(why)}</li>
          {/each}
        </ul>
      {/if}
    </section>

    <!-- Good to know: the FAA now, weather alerts and waivers, each with its time. -->
    <div class="fl-cards">
      <div class="fl-card" data-testid="flights-faa">
        <p class="fl-card-title">
          {faaShown ? flightsCopy.faa.title : flightsCopy.faa.titleOld}
        </p>
        {#if entry.programs === null || live.file.programs_at === null}
          <p class="fl-text">{flightsCopy.faa.notRead}</p>
        {:else if !faaShown}
          <!-- Read, but past its limit: what it said, in gray with its age, never as now (D7). -->
          {#each entry.programs.length === 0 ? [null] : programsBySeverity(entry.programs) as program, i (i)}
            <p class="fl-note" data-testid="flights-faa-old">
              {program === null
                ? flightsCopy.faa.none
                : programLine(programName(program.program) ?? '', program.minutes)}
            </p>
          {/each}
          <p class="fl-note">{faaAge(faaMinutes, true)}</p>
        {:else if entry.programs.length === 0}
          <p class="fl-text">{flightsCopy.faa.none}</p>
          <p class="fl-small">{faaAge(faaMinutes, false)}</p>
        {:else}
          {#each faaPrograms(live, entry, now) as program, i (i)}
            <p class="fl-text">
              {programLine(
                programName(program.program) ?? '',
                program.minutes,
                programEnded(program, now) ? programEndClock(program, zone ?? 'UTC') : null,
              )}
            </p>
            {@const why = programWhy(program.why)}
            {#if why !== null}<p class="fl-small">{why}</p>{/if}
          {/each}
          <p class="fl-small">{faaAge(faaMinutes, false)}</p>
        {/if}
        {#if dayNote !== null}<p class="fl-small">{dayNote}</p>{/if}
      </div>
      {#if entry.alerts !== null && entry.alerts.length > 0 && !stale}
        <div class="fl-card">
          <p class="fl-card-title">{flightsCopy.alerts.title}</p>
          {#each entry.alerts as alert, i (i)}
            <p class="fl-text">{alertName(alert)}</p>
          {/each}
        </div>
      {/if}
      <div class="fl-card" data-testid="flights-waivers">
        <p class="fl-card-title">{flightsCopy.waiver.title}</p>
        {#if waiverLines === null || airlines.length === 0}
          <p class="fl-text">{flightsCopy.waiver.notCheckedAtAirport}</p>
        {:else}
          {#each waiverLines.found as line, i (i)}
            {#if line.state === 'waiver'}
              <p class="fl-text">{waiverFound(line.airline, code, shownDay.day, line.minutes)}</p>
            {/if}
          {/each}
          {#each waiverLines.unclear as line, i (i)}
            {#if line.state === 'unclear'}
              <p class="fl-text">{waiverUnclear(line.airline, line.minutes)}</p>
            {/if}
          {/each}
          {#if waiverLines.none.length > 0}
            <p class="fl-text">
              {waiverNoneMany(waiverLines.none, code, shownDay.day, waiverLines.noneMinutes)}
            </p>
          {/if}
          {#if waiverLines.notChecked.length > 0}
            <p class="fl-text">{waiverNotCheckedMany(waiverLines.notChecked)}</p>
          {/if}
        {/if}
        {#if waiverLines !== null && regionals.length > 0}
          <p class="fl-small">{regionalLine(regionals)}</p>
        {/if}
      </div>
    </div>
  {/if}

  <RecordBox {code} {files} />
</PanelShell>

<style>
  .fl-usual-note {
    margin-top: 8px;
  }

  .is-old :global(.fl-value) {
    color: var(--text-3);
  }

  .is-old :global(.fl-bar span) {
    background: var(--text-3);
  }
</style>
