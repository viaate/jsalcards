<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import type { Attachment } from 'svelte/attachments';

  import { flightsCopy, flightName, routeName, sectionName, updated } from '../../copy-flights';
  import type { Basemap } from '../../map/basemap';
  import AirportPanel from './AirportPanel.svelte';
  import FlightPanel from './FlightPanel.svelte';
  import RecordPanel from './RecordPanel.svelte';
  import RoutePanel from './RoutePanel.svelte';
  import type { RouteBack } from './schedule';
  import StormsPanel from './StormsPanel.svelte';
  import TripsPanel from './TripsPanel.svelte';
  import { TripsHost } from './trips-host.svelte';
  import type { Trip } from './trips';
  import { tripsCopy } from '../../copy-trips';
  import { localToday } from './chance';
  import { backOf, backState, hrefOfView, sameView, viewOfSearch } from './address';
  import type { FlightsView } from './address';
  import { dotStates, dotStatesInTurns } from './layer';
  import { POLL_MS, isStale } from './data';
  import type { Airport, FlightsFiles, LiveRead, WaiversRead } from './data';
  import { mountFlightsLayer } from './layer';
  import type { FlightsLayer } from './layer';
  import { searchFlights } from './search';
  import type { FlightsOption } from './search';
  import './flights.css';

  interface Props {
    map: Basemap;
    header: HTMLElement;
    files: FlightsFiles;
    signal: AbortSignal;
  }

  let { map, header, files, signal }: Props = $props();

  /**
   * The page's controls over the map, as App's CONTROLS names them for the map's labels: the
   * code tags keep clear of them too, and of the map's own buttons.
   */
  const CONTROLS =
    '.wordmark, .search, .menu-button, .account, .updated, .legend, .map-day, .later-key, .locate, .detail, .menu, .mode-own, .maplibregl-ctrl';

  const LIST_ID = 'flights-results';

  /** The account's trips (D12): read only once a panel that shows them opens. */
  const tripsAlive = new AbortController();
  const trips = new TripsHost(tripsAlive.signal);
  onDestroy(() => {
    tripsAlive.abort();
  });

  let airports = $state<readonly Airport[] | null>(null);
  let live = $state<LiveRead | null>(null);
  /** Whether the live file has been asked for at least once, and whether the last ask failed. */
  let tried = $state(false);
  let waivers = $state<WaiversRead | null>(null);
  let now = $state(Date.now());
  let view = $state<FlightsView>(viewOfSearch(location.search));
  let query = $state('');
  let focused = $state(false);
  let active = $state(-1);
  let menuOpen = $state(false);
  let inputElement = $state<HTMLInputElement>();
  let menuButton = $state<HTMLButtonElement>();
  let menuElement = $state<HTMLElement>();
  let layer: FlightsLayer | null = null;
  /** The dots' states last drawn, for the live file they were drawn from. */
  let shownStates: ReturnType<typeof dotStates> | null = null;
  let shownFrom: LiveRead | null = null;
  let shownStale = false;
  /** Set once the layer is on the map, so the effects that draw on it run again. */
  let layerUp = $state(false);

  const byCode = $derived(new Map((airports ?? []).map((airport) => [airport.code, airport])));
  const zones = $derived(new Map((airports ?? []).map((airport) => [airport.code, airport.tz])));
  /** The saved trip open (`&page=trips&trip=<id>`), once the trips are read. */
  const openTrip = $derived.by(() => {
    const id = view.kind === 'trips' ? view.trip : null;
    return id === null ? null : (trips.trips.find((trip) => trip.id === id) ?? null);
  });
  /** Its day as the flight panel counts days: from today at the airport it leaves from. */
  const tripDay = $derived.by(() => {
    const zone = openTrip === null ? undefined : byCode.get(openTrip.from)?.tz;
    if (openTrip === null || zone === undefined) return 0;
    const today = localToday(zone, now);
    return Math.round(
      (Date.parse(`${openTrip.day}T12:00:00Z`) - Date.parse(`${today}T12:00:00Z`)) / 86_400_000,
    );
  });

  function showTrip(trip: Trip): void {
    go({ kind: 'trips', trip: trip.id });
    void focusPanel();
  }

  // A flight or a trip shows whether it is saved: the trips are read once one opens.
  $effect(() => {
    if (view.kind === 'flight' || view.kind === 'trips') trips.load();
  });
  const openAirport = $derived(
    view.kind === 'airport'
      ? view.code
      : view.kind === 'flight' || view.kind === 'route'
        ? view.from
        : null,
  );
  const options = $derived<FlightsOption[]>(
    airports === null ? [] : searchFlights(airports, query, openAirport, LIST_ID),
  );
  const listed = $derived(focused && query.trim() !== '' && airports !== null);
  /** The fade the key, the update line, the search field and the menu come in with (the CSS). */
  const FADE_MS = 200;
  const age = $derived(live === null ? null : (now - live.at) / 60_000);

  /**
   * Puts `node` (a wrapper this component made, drawn as if its children stood in the strip
   * themselves) in the top strip, before Schools' own field, while this mode shows, and takes it
   * away as the mode stops. The component's own root never leaves the stage: Svelte takes a
   * component away by its root nodes, so a moved root would take the strip's other parts with it.
   */
  const inHeader: Attachment<HTMLElement> = (node) => {
    const before = header.querySelector(':scope > .search:not(.mode-own)');
    header.insertBefore(node, before);
    return () => {
      node.remove();
    };
  };

  /** What had the focus when a panel opened from the map: the focus goes back to it on close. */
  let opener: HTMLElement | null = null;
  /**
   * A flight opened from a row of a route's Best time to fly: Close and Escape go back to that
   * route, its cell picked, and give the focus to the row (TRAV-R12-S1, TRAV-R13-S1). `route`:
   * null when the flight's entry was come back to by Forward, whose route is the entry before it.
   */
  let fromRoute: { route: FlightsView | null; back: RouteBack } | null = null;
  /** The cell and row the route panel opens on and focuses, once, coming back from a flight. */
  let routeBack = $state<RouteBack | null>(null);

  /** The history entry's state, or null where the page cannot read it. */
  function entryState(): unknown {
    try {
      return history.state as unknown;
    } catch {
      return null;
    }
  }

  function go(next: FlightsView, push = true, state: unknown = null): void {
    if (sameView(next, view)) return;
    routeBack = null;
    // A new entry is never the flight a route opened: openFlight sets it again after this.
    if (push || next.kind !== 'flight') fromRoute = null;
    if (view.kind === 'home' && next.kind !== 'home') {
      const active = document.activeElement;
      opener = active instanceof HTMLElement && active !== document.body ? active : null;
    }
    view = next;
    try {
      if (push) history.pushState(state, '', hrefOfView(location.href, next));
      else history.replaceState(history.state, '', hrefOfView(location.href, next));
    } catch {
      // The address could not change: the panel still opens.
    }
  }

  /** Whether `node` brings up a phone's keyboard when it takes the focus. */
  const typesIn = (node: HTMLElement): boolean =>
    node instanceof HTMLInputElement ||
    node instanceof HTMLTextAreaElement ||
    node.isContentEditable;

  /**
   * Back to the map. The focus goes back to what opened the panel, never to the page itself, so a
   * screen reader that taps keeps its place too (TRAV-R13-S1): for a keyboard, to the search field
   * when nothing on the page did (a link's panel); for a tap, never to a field, so a phone's
   * keyboard does not come up, but to the map. A flight opened from a route's row goes back to
   * that route's own history entry, so Close and Back are one step and keep the cell picked
   * (TRAV-R13-S2).
   */
  function close(): void {
    const keyboard = document.activeElement?.matches(':focus-visible') === true;
    if (view.kind === 'flight' && fromRoute !== null) {
      const { route, back: row } = fromRoute;
      fromRoute = null;
      if (backOf(entryState()) !== null) {
        try {
          history.back();
          return;
        } catch {
          // No history to go back in: the route opens as a new entry below.
        }
      }
      if (route === null) return;
      go(route);
      routeBack = row;
      return;
    }
    const back = opener;
    opener = null;
    go({ kind: 'home' });
    void tick().then(() => {
      const target = back?.isConnected === true && back.getClientRects().length > 0 ? back : null;
      if (keyboard) (target ?? inputElement)?.focus();
      else if (target !== null && !typesIn(target)) target.focus({ preventScroll: true });
      else map.map.getCanvas().focus({ preventScroll: true });
    });
  }

  /**
   * A usual flight picked in Best time to fly: its own panel, on the day picked, with the focus in
   * it as after a search pick (TRAV-R12-S1). `back`: the route's cell and row it was picked from.
   */
  function openFlight(carrier: string, number: number, day: number, back?: RouteBack): void {
    if (view.kind !== 'route' && view.kind !== 'flight') return;
    const route = view.kind === 'route' ? view : null;
    const kept = route !== null && back !== undefined ? back : null;
    // The route's own entry keeps the cell and row, so Back comes to them too (TRAV-R13-S2).
    if (kept !== null)
      try {
        history.replaceState(backState(history.state, kept), '');
      } catch {
        // Not kept: Close still comes back to them.
      }
    go(
      { kind: 'flight', carrier, number, from: view.from, day },
      true,
      kept === null ? null : backState(null, kept),
    );
    if (route !== null && kept !== null) fromRoute = { route, back: kept };
    void focusPanel();
  }

  function setDay(day: number): void {
    if (view.kind === 'flight') go({ ...view, day }, false);
  }

  /** Where the open flight lands, once its panel has found it: its arc and both ends in view. */
  let landing = $state<{ readonly flight: string; readonly to: string } | null>(null);
  const flightKey = (open: FlightsView): string | null =>
    open.kind === 'flight' ? `${open.carrier}${String(open.number)}-${open.from}` : null;

  function showRoute(to: string): void {
    const flight = flightKey(view);
    if (flight !== null) landing = { flight, to };
  }

  /** The room the panel takes: beside it on a desktop, the phone's sheet below. */
  function panelPadding(): { top: number; bottom: number; left: number; right: number } {
    return window.matchMedia('(max-width: 719px)').matches
      ? { top: 150, bottom: Math.round(window.innerHeight * 0.55), left: 40, right: 40 }
      : { top: 100, bottom: 80, left: 520, right: 80 };
  }

  const motion = (): number =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 600;

  /** Both ends of a route in view, clear of the panel (beside it, or above the phone's sheet). */
  function fitRoute(from: Airport, to: Airport): void {
    map.map.fitBounds(
      [
        [Math.min(from.lon, to.lon), Math.min(from.lat, to.lat)],
        [Math.max(from.lon, to.lon), Math.max(from.lat, to.lat)],
      ],
      { padding: panelPadding(), maxZoom: 7, duration: motion() },
    );
  }

  /**
   * An airport at zoom 6 in the middle of the map left clear of the panel, as a route's ends are:
   * a fit, which leaves the map's own padding as it was (a flight with padding would keep it).
   */
  function showAirport(airport: Airport): void {
    map.map.fitBounds(
      [
        [airport.lon, airport.lat],
        [airport.lon, airport.lat],
      ],
      { padding: panelPadding(), maxZoom: 6, duration: motion() },
    );
  }

  function openStorm(id: string | null): void {
    go(id === null ? { kind: 'storms' } : { kind: 'storm', id });
  }

  /** A result's first line: the code and the city, the route, or the flight. */
  function nameOf(option: FlightsOption): string {
    const hit = option.hit;
    if (hit.kind === 'airport') {
      const airport = byCode.get(hit.code);
      return airport === undefined ? hit.code : `${hit.code} ${airport.city}`;
    }
    if (hit.kind === 'route') return routeName(hit.from, hit.to);
    return flightName(hit.carrier, hit.number);
  }

  /** Its second line: the airport's name, the cities, or the airport the flight leaves from. */
  function subOf(option: FlightsOption): string | null {
    const hit = option.hit;
    if (hit.kind === 'airport') return byCode.get(hit.code)?.name ?? null;
    if (hit.kind === 'route') {
      const from = byCode.get(hit.from);
      const to = byCode.get(hit.to);
      return from === undefined || to === undefined ? null : routeName(from.city, to.city);
    }
    if (hit.from === null) return flightsCopy.search.flightNeedsAirport;
    return byCode.get(hit.from)?.city ?? null;
  }

  /** After a pick the panel takes focus, as Schools' does, so the keyboard goes on from there. */
  async function focusPanel(): Promise<void> {
    await tick();
    document.querySelector<HTMLElement>('.mode-ui .detail')?.focus({ preventScroll: true });
  }

  function pick(option: FlightsOption): void {
    const hit = option.hit;
    if (hit.kind === 'flight' && hit.from === null) {
      query = `${flightName(hit.carrier, hit.number)} `;
      inputElement?.focus();
      return;
    }
    focused = false;
    inputElement?.blur();
    query = nameOf(option);
    fromRoute = null;
    if (hit.kind === 'airport') go({ kind: 'airport', code: hit.code });
    else if (hit.kind === 'route') go({ kind: 'route', from: hit.from, to: hit.to, day: 0 });
    else if (hit.from !== null)
      go({ kind: 'flight', carrier: hit.carrier, number: hit.number, from: hit.from, day: 0 });
    void focusPanel();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!listed || options.length === 0) return;
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      active = (active + step + options.length) % options.length;
    } else if (event.key === 'Enter') {
      const option = options[active >= 0 ? active : 0];
      if (option !== undefined) pick(option);
    } else if (event.key === 'Escape') {
      focused = false;
      inputElement?.blur();
    }
  }

  /**
   * Escape outside the search field closes the open panel, as it closes a school's in Schools
   * (App's onShortcut), and gives a keyboard its focus back as Close does; the menu first.
   */
  function onShortcut(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return;
    if (event.target instanceof Element && event.target.closest('.search') !== null) return;
    if (menuOpen) {
      event.preventDefault();
      closeMenu();
      return;
    }
    if (view.kind === 'home') return;
    event.preventDefault();
    close();
  }

  /**
   * Closes the menu, and gives its button the focus back when the keyboard was in the menu (or
   * nowhere, as after a press inside it), as Schools' menu does (MenuPanel).
   */
  function closeMenu(): void {
    const focus = document.activeElement;
    const held = focus === null || focus === document.body || menuElement?.contains(focus) === true;
    menuOpen = false;
    if (held) menuButton?.focus({ preventScroll: true });
  }

  /**
   * Open, the menu takes the focus, so the keyboard and a screen reader start in it, as in
   * Schools; a press or the focus anywhere else closes it.
   */
  function menuFocus(element: HTMLElement): () => void {
    element.focus({ preventScroll: true });
    const onElsewhere = (event: Event): void => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (element.contains(target) || menuButton?.contains(target) === true) return;
      menuOpen = false;
    };
    window.addEventListener('pointerdown', onElsewhere, true);
    window.addEventListener('focusin', onElsewhere, true);
    return () => {
      window.removeEventListener('pointerdown', onElsewhere, true);
      window.removeEventListener('focusin', onElsewhere, true);
    };
  }

  /** The airport of the past storm day open, whose map it frames instead of today's (D14). */
  const pastAirport = $derived(
    view.kind === 'storm' ? (byCode.get(view.id.split('-')[0] ?? '') ?? null) : null,
  );

  // The map follows what is open: the airport, or both ends of a flight or route.
  $effect(() => {
    const current = view;
    const known = byCode;
    if (!layerUp || layer === null) return;
    const lands = landing;
    if (current.kind === 'airport') {
      layer.select(current.code);
      layer.route(null, null);
      const airport = known.get(current.code);
      if (airport !== undefined) showAirport(airport);
    } else if (current.kind === 'route' || current.kind === 'flight') {
      layer.select(current.from);
      const from = known.get(current.from) ?? null;
      // A flight's other end once its panel has found where it lands (showRoute).
      const toCode =
        current.kind === 'route'
          ? current.to
          : lands !== null && lands.flight === flightKey(current)
            ? lands.to
            : null;
      const to = toCode === null ? null : (known.get(toCode) ?? null);
      layer.route(from, to);
      if (from !== null && to !== null) fitRoute(from, to);
    } else if (current.kind === 'trips' && openTrip !== null) {
      // A saved trip: both its ends and its arc, as a flight's (D21 pattern 7).
      layer.select(openTrip.from);
      const from = known.get(openTrip.from) ?? null;
      const to = known.get(openTrip.to) ?? null;
      layer.route(from, to);
      if (from !== null && to !== null) fitRoute(from, to);
    } else if (pastAirport !== null) {
      // A past day frames its own airport, with none of today's tags beside it (below).
      layer.select(pastAirport.code);
      layer.route(null, null);
      showAirport(pastAirport);
    } else {
      layer.select(null);
      layer.route(null, null);
    }
  });

  // A panel with waiver lines reads the waivers file as it opens.
  $effect(() => {
    const kind = view.kind;
    if (kind !== 'airport' && kind !== 'flight' && kind !== 'trips') return;
    void files.waivers().then((read) => {
      waivers = read;
    });
  });

  /** Whether what is shown is old: at each tick of the clock, so a page that cannot read again turns gray. */
  const liveStale = $derived(isStale(live, now));
  /** The key goes gray with the tags once a file read is old (none read yet is not old). */
  const keyOld = $derived(live !== null && liveStale);

  // The dots follow the live file, and turn gray the moment it is old.
  $effect(() => {
    // While a past storm day is open, today's tags never stand beside it: no file's states, as
    // before any read (D14: a past day is never mixed with live data).
    const read = pastAirport === null ? live : null;
    const old = pastAirport === null && liveStale;
    if (!layerUp || layer === null) return;
    if (read === shownFrom && old === shownStale && shownStates !== null) return;
    shownFrom = read;
    shownStale = old;
    const states = dotStates(read, zones, Date.now());
    shownStates = states;
    layer.show(states, old);
  });

  onMount(() => {
    // The map's own name, for a screen reader, says what it shows here; Schools' comes back after.
    const canvas = map.map.getCanvas();
    const schoolsLabel = canvas.getAttribute('aria-label');
    canvas.setAttribute('aria-label', flightsCopy.mapLabel);
    const alive = new AbortController();
    const stopped = (): boolean => alive.signal.aborted;
    const poll = async (): Promise<void> => {
      const next = await files.live();
      if (stopped()) return;
      tried = true;
      // A failed read keeps what was shown, which turns gray with its age; never a blank map.
      if (next !== null) live = next;
      now = Date.now();
      // The waivers file only once a panel shows a waiver line (W8), never at the first view.
      if (view.kind !== 'airport' && view.kind !== 'flight' && view.kind !== 'trips') return;
      const read = await files.waivers();
      if (stopped()) return;
      waivers = read;
    };
    const firstRead = poll();
    void files.airports().then((rows) => {
      if (stopped() || rows === null) return;
      airports = rows;
      // The layer goes on once the first live read is in (or has failed), so the map takes the
      // points once, with their colors.
      const mountLayer = (read: LiveRead | null, states: ReturnType<typeof dotStates>): void => {
        if (stopped()) return;
        shownStates = states;
        shownFrom = read;
        shownStale = isStale(read, Date.now());
        layer = mountFlightsLayer(
          map,
          rows,
          (code) => {
            go({ kind: 'airport', code });
          },
          signal,
          { states, stale: isStale(read, Date.now()) },
          () => (header.closest('.stage') ?? document).querySelectorAll(CONTROLS),
        );
        layerUp = true;
      };
      // As soon as the style is in (its sources may still be loading): with the map's first
      // frames, never drawing them again. Before the style is in, adding a layer throws; the next
      // style event tries again.
      void firstRead.then(async () => {
        // Every airport's day, reckoned in turns of its own before the layer goes on.
        const read = live;
        const zonesOf = new Map(rows.map((row) => [row.code, row.tz]));
        const states = await dotStatesInTurns(read, zonesOf, Date.now());
        if (stopped()) return;
        // Adding the layer's images fires the map's own style events: a mount under way is never
        // started again from inside itself, which would draw every airport's day once an image.
        let mounting = false;
        const tryMount = (): void => {
          if (layerUp || mounting || stopped()) return;
          mounting = true;
          try {
            mountLayer(read, states);
            map.map.off('styledata', tryMount);
          } catch {
            // Not yet.
          } finally {
            mounting = false;
          }
        };
        // After the next paint and the key's and update line's fade (FADE_MS): the words the
        // read just gave show whole first, so the work of drawing every airport never holds up
        // the page's first words.
        requestAnimationFrame(() => {
          window.setTimeout(() => {
            if (layerUp || stopped()) return;
            map.map.on('styledata', tryMount);
            tryMount();
          }, FADE_MS + 50);
        });
      });
    });
    const timer = window.setInterval(() => void poll(), POLL_MS);
    const clock = window.setInterval(() => (now = Date.now()), 30_000);
    // A flight's entry come back to by a reload: Close still goes back to its route's entry.
    const reloaded = backOf(entryState());
    if (reloaded !== null && view.kind === 'flight') fromRoute = { route: null, back: reloaded };
    const onPop = (): void => {
      if (new URLSearchParams(location.search).get('mode') !== 'flights') return;
      // Back and Forward come to an entry with its cell and row as they were (TRAV-R13-S2).
      const kept = backOf(entryState());
      routeBack = null;
      fromRoute = null;
      view = viewOfSearch(location.search);
      if (kept === null) return;
      if (view.kind === 'route') routeBack = kept;
      else if (view.kind === 'flight') fromRoute = { route: null, back: kept };
    };
    window.addEventListener('popstate', onPop);
    return () => {
      alive.abort();
      window.clearInterval(timer);
      window.clearInterval(clock);
      window.removeEventListener('popstate', onPop);
      layer?.remove();
      if (schoolsLabel === null) canvas.removeAttribute('aria-label');
      else canvas.setAttribute('aria-label', schoolsLabel);
    };
  });
</script>

<svelte:window onkeydown={onShortcut} />

<div class="mode-ui">
  <!-- The search and the menu, in the top strip where Schools' own are, in their look. -->
  <div class="fl-head mode-own" {@attach inHeader}>
    <form
      class="search mode-own"
      class:has-query={query !== ''}
      role="search"
      onsubmit={(event) => {
        event.preventDefault();
      }}
      onfocusout={(event) => {
        const next = event.relatedTarget;
        if (!(next instanceof Node) || !(event.currentTarget as HTMLElement).contains(next))
          focused = false;
      }}
    >
      <svg class="search-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <circle cx="7" cy="7" r="4.75" />
        <path d="M10.5 10.5l3.5 3.5" />
      </svg>
      <input
        class="search-input"
        type="search"
        name="fq"
        bind:this={inputElement}
        bind:value={query}
        placeholder={flightsCopy.search.placeholder}
        aria-label={flightsCopy.search.label}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={listed && options.length > 0}
        aria-controls={listed && options.length > 0 ? LIST_ID : undefined}
        aria-activedescendant={listed ? options[active]?.id : undefined}
        autocomplete="off"
        autocapitalize="characters"
        spellcheck="false"
        enterkeyhint="search"
        onfocus={() => (focused = true)}
        oninput={() => {
          active = -1;
          focused = true;
        }}
        onkeydown={onKeydown}
      />
      {#if query !== ''}
        <button
          class="search-clear"
          type="button"
          aria-label={flightsCopy.search.clear}
          onclick={() => {
            query = '';
            inputElement?.focus();
          }}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
          </svg>
        </button>
      {/if}
      {#if listed}
        <div class="fl-results mode-results">
          {#if options.length > 0}
            <div
              class="fl-results-list"
              id={LIST_ID}
              role="listbox"
              aria-label={flightsCopy.search.results}
            >
              {#each options as option, index (option.id)}
                {@const sub = subOf(option)}
                <div
                  id={option.id}
                  class="fl-option"
                  class:is-target={index === (active >= 0 ? active : 0)}
                  role="option"
                  tabindex="-1"
                  aria-selected={index === active}
                  onpointerdown={(event) => {
                    event.preventDefault();
                  }}
                  onclick={() => {
                    pick(option);
                  }}
                  onkeydown={(event) => {
                    if (event.key === 'Enter') pick(option);
                  }}
                >
                  <span class="fl-option-kind">{sectionName(option.hit.kind)}</span>
                  <span class="fl-option-name">{nameOf(option)}</span>
                  {#if sub !== null}<span class="fl-option-sub">{sub}</span>{/if}
                </div>
              {/each}
            </div>
          {:else}
            <p class="fl-results-none">{flightsCopy.search.none}</p>
          {/if}
        </div>
      {/if}
    </form>
    <button
      class="menu-button mode-own"
      type="button"
      aria-label={flightsCopy.menu.label}
      aria-expanded={menuOpen}
      aria-controls="flights-menu"
      bind:this={menuButton}
      onclick={() => {
        if (menuOpen) closeMenu();
        else menuOpen = true;
      }}
    >
      <span class="menu-lines" aria-hidden="true"></span>
    </button>
  </div>

  {#if menuOpen}
    <nav
      class="fl-menu mode-menu"
      id="flights-menu"
      aria-label={flightsCopy.menu.label}
      tabindex="-1"
      bind:this={menuElement}
      {@attach menuFocus}
    >
      <button
        type="button"
        onclick={() => {
          menuOpen = false;
          go({ kind: 'storms' });
        }}>{flightsCopy.menu.storms}</button
      >
      <button
        type="button"
        onclick={() => {
          menuOpen = false;
          go({ kind: 'record' });
        }}>{flightsCopy.menu.record}</button
      >
      <button
        type="button"
        onclick={() => {
          menuOpen = false;
          go({ kind: 'trips', trip: null });
        }}>{tripsCopy.menu}</button
      >
    </nav>
  {/if}

  <!-- The key: the map's code tags in small, light gray for low risk, a thick amber outline for some risk, solid blue for a high risk, hollow for a usual rate. -->
  <ul
    class="legend flights-legend"
    class:is-old={keyOld}
    aria-label={keyOld ? flightsCopy.legend.old : flightsCopy.legend.label}
  >
    <li>
      <span class="fl-key" data-level="low" aria-hidden="true"></span>{flightsCopy.legend.low}
    </li>
    <li>
      <span class="fl-key" data-level="delay" aria-hidden="true"></span>{flightsCopy.legend.delay}
    </li>
    <li>
      <span class="fl-key" data-level="cancel" aria-hidden="true"></span>{flightsCopy.legend.cancel}
    </li>
    <li><span class="fl-key is-usual" aria-hidden="true"></span>{flightsCopy.legend.usual}</li>
  </ul>

  {#if live !== null && age !== null}
    <p class="fl-updated mode-updated mode-own" class:is-old={liveStale} role="status">
      <time datetime={live.file.generated_at}>{updated(age, liveStale)}</time>
    </p>
  {:else if tried}
    <p class="fl-updated mode-updated mode-own is-old" role="status">{flightsCopy.live.notRead}</p>
  {/if}

  {#if view.kind === 'airport'}
    <AirportPanel
      code={view.code}
      airport={byCode.get(view.code) ?? null}
      {live}
      failed={tried && live === null}
      {waivers}
      {files}
      {now}
      onclose={close}
      onsettle={() => {
        map.controlsChanged();
      }}
    />
  {:else if view.kind === 'route'}
    <RoutePanel
      from={byCode.get(view.from) ?? null}
      to={byCode.get(view.to) ?? null}
      day={view.day}
      {byCode}
      {live}
      failed={tried && live === null}
      {files}
      {now}
      back={routeBack}
      onclose={close}
      onflight={openFlight}
      onsettle={() => {
        map.controlsChanged();
      }}
    />
  {:else if view.kind === 'flight'}
    <FlightPanel
      carrier={view.carrier}
      number={view.number}
      from={byCode.get(view.from) ?? null}
      day={view.day}
      {byCode}
      {live}
      failed={tried && live === null}
      {waivers}
      {files}
      {now}
      onday={setDay}
      onroute={showRoute}
      onflight={openFlight}
      onclose={close}
      onsettle={() => {
        map.controlsChanged();
      }}
      host={trips}
    />
  {:else if view.kind === 'trips' && openTrip !== null}
    <FlightPanel
      carrier={openTrip.carrier}
      number={openTrip.number}
      from={byCode.get(openTrip.from) ?? null}
      day={tripDay}
      {byCode}
      {live}
      failed={tried && live === null}
      {waivers}
      {files}
      {now}
      onday={(day: number) => {
        go({
          kind: 'flight',
          carrier: openTrip.carrier,
          number: openTrip.number,
          from: openTrip.from,
          day,
        });
      }}
      onroute={() => undefined}
      onflight={() => undefined}
      onclose={() => {
        go({ kind: 'trips', trip: null });
      }}
      onsettle={() => {
        map.controlsChanged();
      }}
      host={trips}
      tripTo={openTrip.to}
    />
  {:else if view.kind === 'trips'}
    <TripsPanel
      host={trips}
      {byCode}
      {live}
      {files}
      {now}
      onopen={showTrip}
      onclose={close}
      onsettle={() => {
        map.controlsChanged();
      }}
    />
  {:else if view.kind === 'storms' || view.kind === 'storm'}
    <StormsPanel
      id={view.kind === 'storm' ? view.id : null}
      {files}
      onopen={openStorm}
      onclose={close}
      onsettle={() => {
        map.controlsChanged();
      }}
    />
  {:else if view.kind === 'record'}
    <RecordPanel
      {files}
      {live}
      {zones}
      failed={tried && live === null}
      onclose={close}
      onsettle={() => {
        map.controlsChanged();
      }}
    />
  {/if}
</div>

<style>
  .fl-head {
    display: contents;
  }

  .fl-results {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    left: 0;
    z-index: 3;
    max-height: calc(
      100dvh - var(--inset-top, 0px) - var(--inset-bottom, 0px) - 2 * var(--edge, 20px) -
        var(--brand-stack, 0px) - var(--bar-height, 44px) - 8px
    );
    overflow-y: auto;
    overscroll-behavior: contain;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 16px;
    box-shadow: 0 16px 40px rgb(var(--shadow) / 0.6);
  }

  .fl-results-list {
    padding: 6px;
  }

  .fl-option {
    display: grid;
    grid-template-columns: 64px minmax(0, 1fr);
    column-gap: 12px;
    align-items: center;
    min-height: 44px;
    padding: 5px 10px;
    cursor: pointer;
    border-radius: 10px;
  }

  .fl-option.is-target {
    background: var(--border-1);
  }

  .fl-option-kind {
    grid-row: span 2;
    font-size: 12px;
    color: var(--text-3);
  }

  .fl-option-name {
    font-size: 14px;
    line-height: 19px;
    color: var(--text-1);
    font-variant-numeric: tabular-nums;
  }

  .fl-option-sub {
    overflow: hidden;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fl-results-none {
    margin: 0;
    padding: 14px 16px;
    font-size: 14px;
    color: var(--text-2);
  }

  .fl-menu {
    position: absolute;
    top: calc(var(--inset-top) + var(--edge) + var(--brand-stack) + var(--bar-height) + 8px);
    right: calc(var(--inset-right) + var(--edge));
    z-index: 4;
    display: flex;
    flex-direction: column;
    min-width: 220px;
    padding: 6px;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 16px;
    outline: none;
    /* Schools' menu card (MenuPanel): its sheen, its ring and its shadow. */
    box-shadow:
      inset 0 1px 0 rgb(var(--sheen) / 0.04),
      0 0 0 1px var(--bg),
      0 16px 40px rgb(var(--shadow) / 0.6);
  }

  .fl-menu button {
    min-height: 44px;
    padding: 0 12px;
    font: inherit;
    font-size: 14px;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 10px;
  }

  .fl-menu button:hover,
  .fl-menu button:focus-visible {
    background: var(--border-1);
    outline: none;
  }

  .flights-legend li {
    width: auto !important;
  }

  /* Each mark a code tag in small, as the map draws it (layer.ts). */
  .fl-key {
    flex: none;
    width: 11px;
    height: 7px;
    background: var(--fl-ink);
    border-radius: 3.5px;
  }

  .fl-key[data-level='low'] {
    background: color-mix(in srgb, var(--text-3) 55%, var(--surface-2));
  }

  /* Some risk: the light tag with a thick outline, told from a high risk's solid tag by shape too. */
  .fl-key[data-level='delay'] {
    background: var(--surface-2);
    box-shadow: inset 0 0 0 2px var(--fl-ink);
  }

  /*
    While the file is old the map draws every tag hollow and gray (layer.ts): the key goes gray
    with it, so it never names a risk the map does not show.
  */
  .flights-legend.is-old {
    color: var(--text-3);
  }

  /* The hollow tag as the map draws it: the search bar's surface and hairline. */
  .flights-legend.is-old .fl-key,
  .fl-key.is-usual {
    background: var(--surface-2);
    box-shadow: inset 0 0 0 1px var(--border-2);
  }

  .fl-updated {
    position: absolute;
    top: calc(var(--inset-top) + var(--edge));
    right: calc(var(--inset-right) + var(--edge) + var(--account-room, 0px));
    z-index: 1;
    display: flex;
    align-items: center;
    height: var(--bar-height);
    margin: 0;
    font-size: 13px;
    font-weight: 450;
    color: var(--text-1);
    white-space: nowrap;
    pointer-events: none;
    text-shadow:
      0 0 2px var(--halo),
      0 0 8px var(--halo);
  }

  .fl-updated.is-old {
    color: var(--text-3);
  }

  /*
    The key, the update line and the search field and menu come in after the page's first paint
    (a link to Flights marks the page before it, so Schools' own never show), faded in from
    nothing as Schools' own update line is: quick and quiet, and never taken for the page's
    largest paint.
    Under reduced motion they come in at once (a fade of a millisecond).
  */
  .fl-updated,
  .flights-legend,
  .fl-head > .search,
  .fl-head > .menu-button {
    animation: fl-appear 200ms ease-out both; /* FADE_MS */
  }

  @keyframes fl-appear {
    from {
      opacity: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .fl-updated,
    .flights-legend,
    .fl-head > .search,
    .fl-head > .menu-button {
      animation-duration: 1ms;
    }
  }

  /* On a phone the strip has no room: the line sits over the key, at the foot. */
  @media (max-width: 719px) {
    .fl-updated {
      top: auto;
      right: auto;
      bottom: calc(var(--inset-bottom) + var(--edge) + var(--control-height) + 8px);
      left: calc(var(--inset-left) + var(--edge));
      height: auto;
      font-size: 12px;
    }
  }
</style>
