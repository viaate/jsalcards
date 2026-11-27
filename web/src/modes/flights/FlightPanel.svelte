<script lang="ts">
  import {
    airlineAlerts,
    airlineName,
    clock,
    dayChance,
    dayName,
    faaAge,
    flightName,
    flightsCopy,
    heroNumber,
    lateFact,
    bothFact,
    usualFacts,
    notInUsual,
    reasonKind,
    whyFact,
    programLine,
    programName,
    programWhy,
    reasonName,
    regionalLine,
    notFoundAt,
    notFoundRegional,
    regionalMatch,
    routeName,
    shortDate,
    stormsFallback,
    updated,
    usualChance,
    usualTimes,
    codesOf,
    faaDayNote,
    liveWait,
    waiverFound,
    waiverNone,
    waiverNotChecked,
    waiverUnclear,
    zoneName,
  } from '../../copy-flights';
  import PanelShell from '../../ui/PanelShell.svelte';
  import type { FlightsAirportLive, FlightsRecord, FlightsRoutes } from '../../types/generated';
  import Hero from './Hero.svelte';
  import type { Fact } from '../../copy-flights';
  import RecordBox from './RecordBox.svelte';
  import BackupPlans from './BackupPlans.svelte';
  import TripTools from './TripTools.svelte';
  import type { TripsHost } from './trips-host.svelte';
  import { flightLegs, rowForDay } from './schedule';
  import { addDays, flightChance, instantOf, localParts, localToday, weekdayIndex } from './chance';
  import {
    AIRLINE_SITES,
    REGIONAL_AIRLINES,
    faaFacts,
    faaLive,
    isStale,
    programsBySeverity,
    faaPrograms,
    programEndClock,
    programEnded,
    waiverState,
  } from './data';
  import type { Airport, FlightsFiles, LiveRead, WaiversRead } from './data';

  interface Props {
    carrier: string;
    number: number;
    from: Airport | null;
    day: number;
    byCode: ReadonlyMap<string, Airport>;
    live: LiveRead | null;
    /** Whether the live file could not be read and none is shown: said so, never as reading. */
    failed: boolean;
    waivers: WaiversRead | null;
    files: FlightsFiles;
    now: number;
    onday: (day: number) => void;
    onroute: (to: string) => void;
    /** Opens another flight from the same airport (a regional flight with this number). */
    onflight: (carrier: string, number: number, day: number) => void;
    onclose: () => void;
    onsettle: () => void;
    /** The account's trips (null: no accounts on this page): Save, the ticket type, Backup plans. */
    host?: TripsHost | null;
    /** Opened from a saved trip: the leg it lands at. */
    tripTo?: string | null;
  }

  let {
    carrier,
    number,
    from,
    day,
    byCode,
    live,
    failed,
    waivers,
    files,
    now,
    onday,
    onroute,
    onflight,
    onclose,
    onsettle,
    host = null,
    tripTo = null,
  }: Props = $props();

  let routes = $state<FlightsRoutes | null | undefined>(undefined);
  /** The leg picked, by where it lands. */
  let leg = $state(0);

  $effect(() => {
    const code = from?.code;
    routes = undefined;
    leg = 0;
    if (code === undefined) return;
    void files.routes(code).then((read) => {
      if (code === from?.code) routes = read;
    });
  });

  /** This flight number's rows from this airport in the newest month it flew, and that month. */
  const found = $derived.by(() => {
    if (routes === null || routes === undefined) return null;
    for (const month of routes.months) {
      const rows = month.flights.filter((f) => f.carrier === carrier && f.number === number);
      if (rows.length > 0) return { month: month.month, rows };
    }
    return null;
  });
  /**
   * Not found: a regional flight from here with the same number, as a ticket for a bigger airline
   * shows it (DL 5489, which the files list as SkyWest's OO 5489; LR-F10.3 leaves the index of
   * those to later). Never "it does not fly from here", which would be false.
   */
  const regional = $derived.by(() => {
    if (found !== null || routes === null || routes === undefined) return null;
    for (const month of routes.months) {
      const row = month.flights.find(
        (f) => f.number === number && f.carrier !== carrier && REGIONAL_AIRLINES.has(f.carrier),
      );
      if (row !== undefined) return row;
    }
    return null;
  });
  const legs = $derived(found === null ? [] : flightLegs(found.rows));
  // A saved trip opens on its own leg; the chips below still pick another.
  $effect(() => {
    if (tripTo === null) return;
    const index = legs.indexOf(tripTo);
    if (index >= 0) leg = index;
  });
  const dest = $derived(legs[leg] ?? legs[0] ?? null);
  const today = $derived(from === null ? null : localToday(from.tz, now));
  const date = $derived(today === null ? null : addDays(today, day));
  // From the clock, so a file that cannot be read again turns gray as it ages (data.ts isStale).
  const stale = $derived(isStale(live, now));
  /** The row for the day shown: the one whose weekdays hold it, else the one that flies most. */
  const flight = $derived(
    found === null || dest === null ? null : rowForDay(found.rows, dest, date),
  );
  const to = $derived(flight === null ? null : (byCode.get(flight.to_airport) ?? null));
  const fromLive = $derived<FlightsAirportLive | null>(
    from === null ? null : (live?.byCode.get(from.code) ?? null),
  );
  const toLive = $derived<FlightsAirportLive | null>(
    to === null ? null : (live?.byCode.get(to.code) ?? null),
  );
  const flies = $derived(
    flight !== null && date !== null && (flight.weekdays & (1 << weekdayIndex(date))) !== 0,
  );
  const chance = $derived(
    flight === null ||
      date === null ||
      from === null ||
      to === null ||
      fromLive === null ||
      toLive === null
      ? null
      : flightChance(
          { entry: fromLive, zone: from.tz },
          { entry: toLive, zone: to.tz },
          date,
          flight.leaves,
          flight.lands,
        ),
  );
  /** Whether it has usually left already on the day shown. */
  const gone = $derived(
    flight !== null &&
      date !== null &&
      from !== null &&
      instantOf(date, flight.leaves, from.tz).getTime() <= now,
  );
  const airline = $derived(airlineName(carrier));

  /** The forecast's reasons at `entry` on local `onDay`. */
  function whysAt(entry: FlightsAirportLive | null, onDay: string): readonly number[] {
    if (entry === null) return [];
    const index = Math.round(
      (Date.parse(`${onDay}T12:00:00Z`) - Date.parse(`${entry.today}T12:00:00Z`)) / 86_400_000,
    );
    return entry.why[index] ?? [];
  }

  $effect(() => {
    if (to !== null) onroute(to.code);
  });

  /** Whether a forecast run was read at `entry` for local `onDay`. */
  function runAt(entry: FlightsAirportLive | null, onDay: string): boolean {
    if (entry === null) return false;
    const index = Math.round(
      (Date.parse(`${onDay}T12:00:00Z`) - Date.parse(`${entry.today}T12:00:00Z`)) / 86_400_000,
    );
    return (entry.runs[index] ?? null) !== null;
  }

  /** The forecast's first reason at the end it leaves from, else where it lands. */
  const forecastReason = $derived.by(() => {
    if (chance === null) return null;
    const code =
      whysAt(fromLive, chance.departDay)[0] ?? whysAt(toLive, chance.arriveDay)[0] ?? null;
    return code === null ? null : reasonName(code);
  });
  /** Whether the flight's cancel chance is the usual rate at both ends (LR-SF1, LR-SF8). */
  const cancelAll = $derived(chance !== null && chance.cancelShare === 'all');
  /** Whether a number shown is the usual rate in whole or in part (LR-SF8). */
  const anyUsual = $derived(
    chance !== null &&
      (chance.cancelShare !== 'none' || (chance.late !== null && chance.lateShare !== 'none')),
  );
  /**
   * The answer's one reason, as "Why" under the headline: none where a number shown is the usual
   * rate in whole or in part, so the forecast's weather never reads as the reason for the usual
   * rate (it is said after the usual rows, as the weather).
   */
  const reason = $derived(anyUsual ? null : forecastReason);
  /**
   * The FAA's live programs at either end, said under the answer as now's (LR-F9) and never
   * counted in it (LR-F4): only for today's flight, as the FAA's state is now's alone.
   */
  const faaUnder = (counted: boolean): Fact[] =>
    live === null || stale || day !== 0
      ? []
      : [
          ...(from === null ? [] : faaFacts(live, fromLive, from.code, from.tz, now, counted)),
          ...(to === null
            ? []
            : faaFacts(live, toLive, to.code, to.tz, now, counted, to.tz !== from?.tz)),
        ];
  /** Under an answer with no number: the facts alone. */
  const faaNow = $derived(faaUnder(false));
  /** Under the flight's chance: with the note that the chance does not count them. */
  const faaCounted = $derived(faaUnder(true));
  /** The flight's two ends, leaving then landing, each with its day's reasons. */
  const endsWhy = $derived(
    chance === null || from === null || to === null
      ? []
      : [
          { code: from.code, whys: whysAt(fromLive, chance.departDay) },
          { code: to.code, whys: whysAt(toLive, chance.arriveDay) },
        ],
  );
  /**
   * The end whose record is said beside a usual cancel chance (LR-SF1): only where the cancel
   * chance is the usual rate at both ends (with a forecast cancel at either end, its headline reads
   * as a forecast, as the airport's does), the first end whose reasons that day name weather the
   * record has a kind for. Null where none does.
   */
  const recordEnd = $derived.by((): { code: string; kind: number; why: number } | null => {
    if (!cancelAll) return null;
    for (const end of endsWhy) {
      const why = end.whys.find((each) => reasonKind(each) !== null);
      const kind = why === undefined ? null : reasonKind(why);
      if (why !== undefined && kind !== null) return { code: end.code, kind, why };
    }
    return null;
  });
  /**
   * The Weather row beside a usual cancel chance, at its airport (LR-SF1): the record end's
   * weather, so the record rows always follow the weather they speak to, else the first end's.
   */
  const weatherEnd = $derived.by((): { code: string; why: number } | null => {
    if (recordEnd !== null) return { code: recordEnd.code, why: recordEnd.why };
    for (const end of endsWhy) {
      const why = end.whys[0];
      if (why !== undefined) return { code: end.code, why };
    }
    return null;
  });
  /** Its code alone, so the clock's ticks never read the record again. */
  const recordCode = $derived(recordEnd?.code ?? null);
  let endRecord = $state<FlightsRecord | null>(null);
  $effect(() => {
    const asked = recordCode;
    endRecord = null;
    if (asked === null) return;
    void files.record(asked).then((read) => {
      if (asked === recordCode) endRecord = read;
    });
  });
  const recordRows = $derived.by((): Fact[] => {
    const read = endRecord;
    if (recordEnd === null || read?.code !== recordEnd.code) return [];
    const { kind } = recordEnd;
    const line = read.lines.find((each) => each.kind === kind) ?? null;
    return notInUsual(kind, line, read.first, recordEnd.code);
  });
  /** The rows under the answer (LR-F18.2): the forecast's reason, then the FAA, then the rest. */
  const heroRows = $derived.by((): Fact[] => {
    const cancel = chance?.cancel ?? null;
    if (chance === null || cancel === null) return faaNow;
    // A live FAA program first, right under the headline (LR-F9): on the first screen, after the
    // answer's one reason.
    const lines: Fact[] = [...(reason === null ? [] : [whyFact(reason)]), ...faaCounted];
    if (chance.late !== null) lines.push(lateFact(chance.late));
    lines.push(bothFact());
    if (anyUsual) {
      // An end is "not ready" only where all its values are usual and no run was read for its
      // day: where a run was read, its own test failed, which the usual rows already say.
      const fromRun = runAt(fromLive, chance.departDay);
      const toRun = runAt(toLive, chance.arriveDay);
      const ends = [
        ...(chance.fromCancelUsual && chance.fromLateUsual && !fromRun && from !== null
          ? [from.code]
          : []),
        ...(chance.toCancelUsual && chance.toLateUsual && !toRun && to !== null ? [to.code] : []),
      ];
      lines.push(
        ...usualFacts({
          cancel: chance.cancelShare,
          late: chance.late === null ? null : chance.lateShare,
          run: fromRun || toRun,
          codes: ends,
          reason: weatherEnd === null ? null : reasonName(weatherEnd.why),
          reasonAt: weatherEnd?.code ?? null,
        }),
      );
    }
    lines.push(...recordRows);
    return lines;
  });

  interface FaaLine {
    readonly text: string;
    readonly why: string | null;
    /** Its dot's level; null for a read past its limit, said in gray with no dot. */
    readonly level: string | null;
  }

  /** The FAA's programs at one end, the gravest first: none hidden behind another. */
  function faaLines(
    entry: FlightsAirportLive | null,
    zone: string | null,
  ): {
    lines: FaaLine[];
    age: string | null;
    /** Whether the lines are the FAA now: the card's title says "now" only then. */
    now: boolean;
    /** How the FAA was read: live, past its limit, or not at all (faaDayNote). */
    read: 'live' | 'old' | 'none';
  } {
    const programs = entry?.programs ?? null;
    const at = live?.file.programs_at ?? null;
    const minutes = at === null ? null : (now - Date.parse(at)) / 60_000;
    if (live === null || programs === null || minutes === null)
      return {
        lines: [{ text: flightsCopy.faa.notRead, why: null, level: 'low' }],
        age: null,
        now: false,
        read: 'none',
      };
    // Read, but past its limit: what it said, in gray with its age, never as now (D7).
    if (!faaLive(live, now))
      return {
        lines: (programs.length === 0 ? [null] : programsBySeverity(programs)).map((program) => ({
          text:
            program === null
              ? flightsCopy.faa.none
              : programLine(programName(program.program) ?? '', program.minutes),
          why: null,
          level: null,
        })),
        age: faaAge(minutes, true),
        now: false,
        read: 'old',
      };
    if (programs.length === 0)
      return {
        lines: [{ text: flightsCopy.faa.none, why: null, level: 'low' }],
        age: faaAge(minutes, false),
        now: true,
        read: 'live',
      };
    return {
      lines: faaPrograms(live, entry, now).map((program) => ({
        text: programLine(
          programName(program.program) ?? '',
          program.minutes,
          programEnded(program, now) && zone !== null ? programEndClock(program, zone) : null,
        ),
        why: programWhy(program.why),
        level: program.program === 0 || program.program === 4 ? 'cancel' : 'delay',
      })),
      age: faaAge(minutes, false),
      now: true,
      read: 'live',
    };
  }

  /**
   * W2's lines for this airline at both ends on the flight's day (and LR-W1's unclear), said once
   * for the trip: the waiver is the airline's, so ends in the same state share one line ("for MCI
   * or LAX"), and a line that names no airport is never said twice.
   */
  function waiverLines(codes: readonly string[], onDay: string): string[] {
    // A regional airline sells no tickets of its own: the waiver is the bigger airline's (W4).
    if (REGIONAL_AIRLINES.has(carrier)) return [regionalLine([airline])];
    const states = codes.map((code) => ({
      code,
      state: waiverState(waivers, carrier, airline, code, onDay, now),
    }));
    const lines: string[] = [];
    const found = states.flatMap((end) => (end.state.state === 'waiver' ? [end.state] : []));
    const foundCodes = states.filter((end) => end.state.state === 'waiver').map((end) => end.code);
    const none = states.flatMap((end) => (end.state.state === 'none_found' ? [end.state] : []));
    const noneCodes = states
      .filter((end) => end.state.state === 'none_found')
      .map((end) => end.code);
    if (found[0] !== undefined)
      lines.push(waiverFound(found[0].airline, codesOf(foundCodes), onDay, found[0].minutes));
    if (none[0] !== undefined)
      lines.push(waiverNone(none[0].airline, codesOf(noneCodes, true), onDay, none[0].minutes));
    for (const { state } of states) {
      const line =
        state.state === 'unclear'
          ? waiverUnclear(state.airline, state.minutes)
          : state.state === 'waiver' || state.state === 'none_found'
            ? null
            : waiverNotChecked(state.airline);
      if (line !== null && !lines.includes(line)) lines.push(line);
    }
    return lines;
  }

  /** The local date it lands, at the arrival airport's clock (for "I need to be there by"). */
  const arriveDate = $derived(
    chance === null || flight === null || date === null || from === null || to === null
      ? null
      : localParts(
          new Date(instantOf(date, flight.leaves, from.tz).getTime() + chance.minutes * 60_000),
          to.tz,
        ).day,
  );

  /** Every leg the number flies from here on the day shown, for Save's leg pick (D19). */
  const dayLegs = $derived(
    found === null
      ? []
      : legs.flatMap((code) => {
          const row = rowForDay(found.rows, code, date);
          return row === null ? [] : [{ to: code, leaves: row.leaves, lands: row.lands }];
        }),
  );
  const saved = $derived(
    host === null || from === null || date === null
      ? null
      : host.find(carrier, number, from.code, date),
  );

  const alertsLink = $derived.by(() => {
    const site = AIRLINE_SITES[carrier];
    if (site === undefined) return null;
    const path = waivers?.airlines.get(carrier)?.path ?? '/';
    return new URL(path, site).href;
  });
</script>

<PanelShell
  label={flightName(carrier, number)}
  shows={`flight:${carrier}${String(number)}-${from?.code ?? ''}`}
  {onclose}
  {onsettle}
>
  {#snippet head()}
    <p class="fl-kind">
      {flightName(carrier, number)}{#if date !== null}&nbsp;·&nbsp;{shortDate(date)}{/if}
    </p>
    <h2 class="fl-name">
      {#if from !== null && to !== null}{routeName(from.city, to.city)}{:else}{flightName(
          carrier,
          number,
        )}{/if}
    </h2>
  {/snippet}

  {#if live === null}
    <p class="fl-note">{liveWait(failed)}</p>
  {:else if routes === undefined}
    <p class="fl-note">{flightsCopy.live.loading}</p>
  {:else if routes === null}
    <p class="fl-note">{flightsCopy.flight.notReady}</p>
  {:else if from !== null && regional !== null}
    <p class="fl-text">
      {regionalMatch(
        airlineName(regional.carrier),
        flightName(regional.carrier, regional.number),
        from.code,
        regional.to_airport,
        clock(regional.leaves),
      )}
    </p>
    <button
      type="button"
      class="fl-row-button"
      data-testid="flights-regional"
      onclick={() => {
        onflight(regional.carrier, regional.number, day);
      }}
      ><span
        >{flightName(regional.carrier, regional.number)}&nbsp;·&nbsp;{routeName(
          from.code,
          regional.to_airport,
        )}&nbsp;·&nbsp;{clock(regional.leaves)}</span
      ></button
    >
  {:else if flight === null || from === null || to === null || found === null || date === null}
    <p class="fl-text">
      {from === null
        ? flightsCopy.flight.notFound
        : notFoundAt(flightName(carrier, number), from.code)}
    </p>
    <p class="fl-note">{notFoundRegional(flightName('OO', number), airlineName('OO'))}</p>
  {:else}
    <!--
      The answer first, with any live FAA program, whole on a phone sheet's first height (D21),
      for the day picked below; the flight card under it.
    -->
    {#if stale && live !== null}
      <Hero
        number={null}
        meaning={updated((now - live.at) / 60_000, true)}
        old
        testid="flights-answer"
      />
    {:else if !flies}
      <Hero number={null} meaning={flightsCopy.flight.notThatDay} testid="flights-answer" />
    {:else if gone}
      <Hero number={null} meaning={flightsCopy.flight.left} testid="flights-answer" />
    {:else if chance === null || chance.answer === 'none' || chance.cancel === null}
      <!-- No number for the day, but a live FAA program is now's all the same (LR-F9). -->
      <Hero
        number={null}
        meaning={flightsCopy.noForecastDay}
        rows={faaNow}
        testid="flights-answer"
      />
    {:else}
      <!-- The flight's own block at each end (LR-F9): its number, never the day's. -->
      <Hero
        number={heroNumber(chance.cancel)}
        meaning={cancelAll ? usualChance(date, null) : dayChance(date, today ?? date, false)}
        rows={heroRows}
        testid="flights-answer"
      />
    {/if}

    <!-- The flight card: both codes big, the usual times large on each end's own clock. -->
    <div class="fl-ends" data-testid="flights-card">
      <div class="fl-end">
        <p class="fl-code">{from.code}</p>
        <p class="fl-small">{from.city}</p>
        <p class="fl-time">{clock(flight.leaves)}</p>
        {#if date !== null}<p class="fl-small">
            {zoneName(from.tz, instantOf(date, flight.leaves, from.tz))}
          </p>{/if}
      </div>
      <span class="fl-line" aria-hidden="true">
        <svg viewBox="0 0 16 16" focusable="false"
          ><path
            d="M8 1.75v12.5M8 5.5L2.25 9v1.25L8 8.5l5.75 1.75V9zM5.75 14.25L8 13l2.25 1.25"
          /></svg
        >
      </span>
      <div class="fl-end">
        <p class="fl-code">{to.code}</p>
        <p class="fl-small">{to.city}</p>
        <p class="fl-time">{clock(flight.lands)}</p>
        {#if date !== null}<p class="fl-small">
            {zoneName(to.tz, instantOf(date, flight.lands, to.tz))}
          </p>{/if}
      </div>
    </div>
    <p class="fl-note">{usualTimes(found.month)}</p>

    {#if legs.length > 1}
      <div class="fl-chips" role="group" aria-label={flightsCopy.flight.title}>
        {#each legs as option, i (option)}
          <button type="button" class="fl-chip" aria-pressed={i === leg} onclick={() => (leg = i)}
            >{routeName(from.code, option)}</button
          >
        {/each}
      </div>
    {/if}

    <div class="fl-chips" role="group" aria-label={flightsCopy.dayGroup}>
      {#each [0, 1, 2] as index (index)}
        {#if today !== null}
          <button
            type="button"
            class="fl-chip"
            aria-pressed={index === day}
            onclick={() => {
              onday(index);
            }}>{dayName(addDays(today, index), today, stale)}</button
          >
        {/if}
      {/each}
    </div>

    {#if host !== null && flies && !gone}
      <TripTools
        {host}
        {carrier}
        {number}
        from={from.code}
        day={date}
        leg={{ to: to.code, leaves: flight.leaves, lands: flight.lands }}
        legs={dayLegs}
        arriveDay={arriveDate ?? date}
      />
    {/if}

    <!-- Good to know: the FAA at each end, and the airline's waiver at each end (W2). -->
    <div class="fl-cards">
      {#each [{ airport: from, entry: fromLive }, { airport: to, entry: toLive }] as end (end.airport.code)}
        {@const faa = faaLines(end.entry, end.airport.tz)}
        {@const dayNote = day > 0 ? faaDayNote(faa.read, 'flight') : null}
        <div class="fl-card" data-testid="flights-end">
          <p class="fl-card-title">
            {end.airport.code}&nbsp;·&nbsp;{faa.now
              ? flightsCopy.faa.title
              : flightsCopy.faa.titleOld}
          </p>
          {#each faa.lines as line, i (i)}
            {#if line.level === null}
              <p class="fl-note" data-testid="flights-faa-old">{line.text}</p>
            {:else}
              <p class="fl-text">{line.text}</p>
            {/if}
            {#if line.why !== null}<p class="fl-small">{line.why}</p>{/if}
          {/each}
          {#if faa.age !== null}<p class="fl-small">{faa.age}</p>{/if}
          {#if dayNote !== null}<p class="fl-small">{dayNote}</p>{/if}
        </div>
      {/each}
      {#if date !== null}
        <!-- The airline's waiver, once for the trip: it is the airline's, not one airport's. -->
        <div class="fl-card" data-testid="flights-waivers">
          <p class="fl-card-title">{flightsCopy.waiver.title}</p>
          {#each waiverLines([from.code, to.code], date) as line (line)}
            <p class="fl-small">{line}</p>
          {/each}
        </div>
      {/if}
      {#if alertsLink !== null}
        <a class="fl-link" href={alertsLink} rel="noopener" target="_blank"
          >{airlineAlerts(airline)}</a
        >
      {/if}
    </div>

    {#if flies && !gone && !stale && live !== null}
      <BackupPlans
        trip={{
          carrier,
          number,
          from: from.code,
          to: to.code,
          day: date,
          leaves: flight.leaves,
          lands: flight.lands,
          needBy: saved?.need_by ?? null,
        }}
        ticket={saved?.ticket ?? 'unsure'}
        {byCode}
        {live}
        {waivers}
        {files}
        {now}
      />
    {/if}

    <!--
      This flight on past storm days (D22): its own counts are not in the published files yet,
      so the card says so plainly and the airport's own record stands in.
    -->
    <RecordBox
      code={from.code}
      {files}
      title={flightsCopy.flight.storms}
      note={stormsFallback(from.code)}
    />
  {/if}
</PanelShell>
