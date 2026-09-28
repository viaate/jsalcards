<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import type { Component } from 'svelte';
  import type { Attachment } from 'svelte/attachments';

  import type {
    NearbyView,
    SchoolHint,
    SchoolView,
    SearchOption,
    Services,
    Target,
  } from './app/boot';
  import { grantedPlace, opensNearby } from './app/nearby';
  import { copy } from './copy';
  import type { Basemap, MapView, Place } from './map/basemap';
  import { loadBasemap } from './map/basemap/load';
  import type { Glow } from './map/glow-mount';
  import { markStep, yieldToMain } from './map/basemap/reveal';
  import { afterFirstPaint } from './shell/paint';
  import { retireStill } from './shell/still';
  import { pinnedSchool } from './state/pin';
  import { createUrlStore } from './state/url-store';
  import type { UrlStore } from './state/url-store';
  import type { Selection } from './state/url';
  import type { SchoolId, UtcInstant } from './types/generated';

  interface Props {
    /** The inline still from index.html, handed over by main.ts. */
    still?: SVGSVGElement | null;
    /** Text typed into the static search field before the app started. */
    initialQuery?: string;
  }

  interface ResultsProps {
    id: string;
    options: readonly SearchOption[];
    active: number;
    onpick: (option: SearchOption) => void;
    onactive: (index: number) => void;
  }

  interface UpdateTimeProps {
    generatedAt: UtcInstant;
  }

  interface DetailProps {
    view: SchoolView;
    pinned: boolean;
    copied: boolean;
    onclose: () => void;
    onpin: () => void;
    onshare: () => void;
    onnearby?: (school: NearbyView) => void;
    element?: HTMLElement | undefined;
  }

  let { still = null, initialQuery = '' }: Props = $props();

  const LIST_ID = 'search-results';

  let stageElement = $state<HTMLElement>();
  let mapElement = $state<HTMLDivElement>();
  let frameElement = $state<HTMLDivElement>();
  let inputElement = $state<HTMLInputElement>();
  let headerElement = $state<HTMLElement>();

  let query = $state(untrack(() => initialQuery));
  /** The newest text's results, or null when there are none to show. */
  let options = $state<readonly SearchOption[] | null>(null);
  /**
   * The highlighted option, which Enter picks, or -1. New results highlight
   * their first option, the best match, so Enter alone goes there and the
   * first Down moves on to the next.
   */
  let active = $state(-1);
  let focused = $state(false);
  /** Escape hides the list until the text changes. */
  let dismissed = $state(false);
  /** The results list, loaded with the search index on first focus. */
  let Results = $state<Component<ResultsProps> | null>(null);
  /** When the live file the map shows was made; null until one is shown. */
  let updatedAt = $state<UtcInstant | null>(null);
  /** The update time, loaded with the first live file shown. */
  let UpdateTime = $state<Component<UpdateTimeProps> | null>(null);
  /** The name the field shows for the last pick, until the text changes. */
  let pickedName: string | null = null;
  /** True while the phone is asked where it is. */
  let locating = $state(false);
  /** What the address opens: a school's panel shows while it holds one. */
  let selection = $state<Selection | null>(null);
  /** The open school's panel, loaded the first time a school opens. */
  let Detail = $state<Component<DetailProps> | null>(null);
  /** The open school's view; null while none is open, or for an id with no school. */
  let schoolView = $state<SchoolView | null>(null);
  let detailElement = $state<HTMLElement>();
  /** The pinned school, once the pin is read. */
  let pinnedId = $state<SchoolId | null>(null);
  /** True for a moment after the panel's link was copied. */
  let copied = $state(false);
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;
  /** What the last pick knew about the school it opened, shown until its record is read. */
  let pickedHint: SchoolHint | null = null;
  /** Whether the panel takes focus when it shows: after a pick, not for a link or the pin. */
  let focusPanel = false;
  /** The address store, once the app has started. */
  let urls: UrlStore | undefined;

  const schoolId = $derived(selection?.kind === 'school' ? selection.id : null);

  const expanded = $derived(
    focused && !dismissed && Results !== null && options !== null && query.trim() !== '',
  );
  const listed = $derived(expanded && options !== null && options.length > 0);

  let basemap: Basemap | undefined;
  /** Where to go once the map exists, for a result picked before it did. */
  let pendingTarget: Target | null = null;
  /** The viewer's place, found before the map existed: their area is its home view. */
  let pendingNear: Place | null = null;
  /** The rest of the app (search, data, glow, offline), loaded after the first paint. */
  let services: Promise<Services | null> = Promise.resolve(null);

  /** The map, once its first frame is up, and the glow layer on it (null when it could not load). */
  interface MapParts {
    basemap: Basemap;
    glow: Glow | null;
  }

  /** The page's controls over the map, which its labels keep clear of (the results list aside). */
  const CONTROLS = '.wordmark, .search, .updated, .legend, .locate, .detail';

  /**
   * Loads MapLibre after the first paint and hands the view over from the
   * still to the WebGL map. At the national view the map draws the still's
   * own lines, and the still fades out over them once the map is up. Anywhere
   * else (a link's view, the viewer's own area) the still goes at once, in
   * the frame the map first shows, so the country is never laid over a
   * street. If the map cannot start (no WebGL), the still simply stays. A
   * link's view opens at the nearest view the map allows on this screen. A
   * phone with nothing linked or pinned opens over its viewer's area when
   * they have already let the site know where they are (app/nearby.ts), read
   * while MapLibre loads. The glow layer's code loads alongside MapLibre's,
   * and the layer goes on with the map's style, so it never makes the map
   * draw its first frames again.
   */
  async function startMap(signal: AbortSignal, links: UrlStore): Promise<MapParts | undefined> {
    // A function, so each check reads the signal afresh after an await.
    const aborted = (): boolean => signal.aborted;
    await afterFirstPaint();
    if (aborted() || mapElement === undefined || frameElement === undefined) return;
    const container = mapElement;
    const frame = frameElement;
    const stage = stageElement;
    let handedOver = false;
    /** The still goes: faded out over the same lines at the national view, at once anywhere else. */
    const handOver = (national: boolean): void => {
      if (handedOver || still === null) return;
      handedOver = true;
      retireStill(still, { fade: national });
      markStep('map-takeover');
    };
    let map: Basemap;
    let glow: Glow | null = null;
    try {
      const loading = Promise.all([loadBasemap(), import('./map/glow-mount').catch(() => null)]);
      // Held until it is awaited below: a download that fails at once is not left unhandled.
      loading.catch(() => undefined);
      // Reading the pin opens the site's storage, a wait of its own: once the downloads are going.
      await yieldToMain();
      const linked =
        links.state.view !== null || links.state.selection !== null || pinnedSchool() !== null;
      const [[factory, glowCode], near] = await Promise.all([
        loading,
        linked || !opensNearby(frame) ? null : grantedPlace(),
      ]);
      markStep('map-loaded');
      // Evaluating MapLibre and creating the map are each sizable; keep them in separate tasks.
      await yieldToMain();
      if (aborted()) return;
      map = await factory.create({
        container,
        frame,
        view: links.state.view,
        near,
        controls: () => stage?.querySelectorAll(CONTROLS) ?? [],
        // Off the national view, the still goes as the map first shows, never over it.
        onReveal: ({ national }) => {
          if (!national) handOver(false);
        },
      });
      if (aborted()) {
        map.destroy();
        return;
      }
      try {
        glow = glowCode?.mountGlow(map.map) ?? null;
      } catch {
        // The map is worth showing without its glow.
      }
    } catch (error) {
      console.warn('Snowlight: map unavailable', error);
      return;
    }
    signal.addEventListener('abort', () => {
      map.destroy();
    });
    basemap = map;
    map.selectSchool(schoolId);
    followLinks(map, links, signal);
    if (pendingNear !== null) map.showNear(pendingNear);
    if (pendingTarget !== null) show(pendingTarget);

    // Someone moving the map before it is up shows it at once (index.ts), and the still goes then.
    await map.ready;
    if (!aborted()) handOver(true);
    return { basemap: map, glow };
  }

  /**
   * Keeps the address bar on the view the map shows (none at the national
   * view), and moves the map when Back or Forward brings back another view.
   */
  function followLinks(map: Basemap, links: UrlStore, signal: AbortSignal): void {
    const record = (): void => {
      // A flight waiting at its stop is on its way: the address keeps where it is going.
      if (map.flightStopped) return;
      links.setView(map.national ? null : map.view);
    };
    // A link outside this screen's limits opened at the nearest allowed view: write that one.
    record();
    map.map.on('moveend', record);
    const stop = links.subscribe((state, origin) => {
      if (origin === 'history') map.goTo(state.view);
    });
    signal.addEventListener('abort', stop);
  }

  /** Moves the map to a place, or keeps it for when the map exists. */
  function show(target: Target): void {
    if (basemap === undefined) {
      pendingTarget = target;
      return;
    }
    pendingTarget = null;
    if ('view' in target) basemap.flyTo(target.view);
    else basemap.fitBounds(target.bounds, { maxZoom: target.maxZoom });
  }

  /** The panel's width and its gap from the edge (DetailPanel.svelte), and a phone's sheet at most. */
  const PANEL_WIDTH = 368;
  const PANEL_EDGE = 20;
  const SHEET_HEIGHT = 520;
  const SHEET_SHARE = 0.64;
  /** MapLibre's tile size in CSS pixels. */
  const TILE = 512;

  /**
   * The view that shows `view`'s middle in the middle of the map the panel
   * leaves in view: right of the panel beside the map, above the sheet on a
   * phone, and below the search strip either way.
   */
  function clearOfPanel(view: MapView): MapView {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const top = headerElement?.getBoundingClientRect().bottom ?? 0;
    const phone = width < 720;
    const covered = phone
      ? { left: 0, bottom: Math.min(SHEET_HEIGHT, height * SHEET_SHARE) }
      : { left: PANEL_EDGE + PANEL_WIDTH, bottom: 0 };
    // Where the place goes, from the screen's middle, in pixels.
    const dx = covered.left / 2;
    const dy = (top + height - covered.bottom) / 2 - height / 2;
    const scale = TILE * 2 ** view.zoom;
    const x = ((view.lon + 180) / 360) * scale - dx;
    const sin = Math.sin((view.lat * Math.PI) / 180);
    const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale - dy;
    const lon = (x / scale) * 360 - 180;
    const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / scale))) * 180) / Math.PI;
    return { lat, lon, zoom: view.zoom };
  }

  function runSearch(text: string): void {
    dismissed = false;
    active = -1;
    if (text.trim() === '') options = null;
    void services.then((app) => {
      app?.query(text);
    });
  }

  function onFocus(): void {
    focused = true;
    // Coming back to the field shows its results again, even ones Escape hid.
    dismissed = false;
    void services.then((app) => {
      if (app?.searchable !== true) return;
      app.warmSearch();
      if (Results === null) {
        import('./ui/SearchResults.svelte').then(
          (module) => {
            Results = module.default;
          },
          () => undefined,
        );
      }
      if (query.trim() !== '' && options === null) runSearch(query);
    });
  }

  function pick(option: SearchOption): void {
    query = option.name;
    pickedName = option.name;
    options = null;
    active = -1;
    if (option.hit.kind === 'school') {
      pickedHint = { id: option.hit.id, name: option.name, sub: option.sub };
      focusPanel = true;
    }
    inputElement?.blur();
    void services.then((app) => {
      app?.pick(option.hit);
    });
  }

  // The school the address holds: its view, read and kept current while it is open.
  $effect(() => {
    const id = schoolId;
    schoolView = null;
    basemap?.selectSchool(id);
    if (id === null) return;
    let stop: () => void = () => undefined;
    let cancelled = false;
    const hint = untrack(() => pickedHint);
    void services.then((app) => {
      if (cancelled || app === null) return;
      stop = app.watchSchool(id, hint, (view) => {
        if (!cancelled) schoolView = view;
      });
    });
    if (untrack(() => Detail) === null) {
      import('./ui/DetailPanel.svelte').then(
        (module) => {
          Detail = module.default;
        },
        () => undefined,
      );
    }
    return () => {
      cancelled = true;
      stop();
    };
  });

  /** Opens a school from the nearby list, as a pick of it would. */
  function openNearby(school: NearbyView): void {
    query = school.name;
    pickedName = school.name;
    pickedHint = { id: school.id, name: school.name, sub: '' };
    void services.then((app) => {
      app?.pick({
        kind: 'school',
        id: school.id,
        name: school.name,
        sub: '',
        state: '',
        lat: school.lat,
        lon: school.lon,
        match: 'exact',
        highlight: [],
      });
    });
  }

  // The panel comes or goes over the map: its labels keep clear of it.
  const panelShown = $derived(Detail !== null && schoolView !== null);
  let panelWasShown = false;
  $effect(() => {
    if (panelShown === panelWasShown) return;
    panelWasShown = panelShown;
    basemap?.controlsChanged();
  });

  // After a pick the panel takes focus, so the keyboard goes on from where the pick lands.
  $effect(() => {
    if (!panelShown || detailElement === undefined || !focusPanel) return;
    focusPanel = false;
    detailElement.focus({ preventScroll: true });
  });

  function closeSchool(): void {
    urls?.select(null);
  }

  function togglePin(): void {
    const id = schoolId;
    if (id === null) return;
    void services.then((app) => {
      if (app === null) return;
      if (app.pins.school === id) app.pins.unpin();
      else app.pins.pin(id);
    });
  }

  /**
   * Shares a link to the open school: the share sheet where the device has
   * one for a thumb, else the link copied, and said so on the button.
   */
  function shareSchool(): void {
    if (urls === undefined || schoolView === null) return;
    const url = urls.shareUrl();
    const title = schoolView.name;
    const touch = window.matchMedia('(pointer: coarse)').matches;
    if (touch && typeof navigator.share === 'function') {
      navigator.share({ title, url }).catch(() => undefined);
      return;
    }
    navigator.clipboard.writeText(url).then(
      () => {
        copied = true;
        clearTimeout(copiedTimer);
        copiedTimer = setTimeout(() => {
          copied = false;
        }, 2000);
      },
      () => undefined,
    );
  }

  function onKeydown(event: KeyboardEvent): void {
    // Keys that confirm or cancel an input method's composition are the input method's.
    if (event.isComposing) return;
    const list = options ?? [];
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        // Down brings back a list Escape hid, as it was.
        if (event.key === 'ArrowDown' && dismissed && query.trim() !== '') {
          event.preventDefault();
          dismissed = false;
          return;
        }
        if (!listed) return;
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        active =
          active < 0 && step < 0 ? list.length - 1 : (active + step + list.length) % list.length;
        const id = list[active]?.id;
        if (id !== undefined) document.getElementById(id)?.scrollIntoView({ block: 'nearest' });
        return;
      }
      case 'Enter': {
        const option = list[Math.max(active, 0)];
        if (!listed || option === undefined) return;
        event.preventDefault();
        pick(option);
        return;
      }
      case 'Escape':
        // The first Escape hides the list and keeps the text; the next one clears it.
        // Chrome clears a search field on Escape by itself: held back whenever the app acts.
        if (expanded) {
          event.preventDefault();
          dismissed = true;
        } else if (query !== '') {
          event.preventDefault();
          query = '';
          runSearch('');
        }
        return;
    }
  }

  /** "/" anywhere but in a text field goes to the search field, as on most sites with search. */
  function onShortcut(event: KeyboardEvent): void {
    // Escape outside the search field closes an open school.
    if (event.key === 'Escape' && !event.defaultPrevented && schoolView !== null) {
      if (event.target instanceof Element && event.target.closest('.search') !== null) return;
      event.preventDefault();
      closeSchool();
      return;
    }
    if (event.key !== '/' || event.defaultPrevented || event.isComposing) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (
      target instanceof Element &&
      target.closest(
        'input, textarea, select, [contenteditable]:not([contenteditable="false"])',
      ) !== null
    ) {
      return;
    }
    if (inputElement === undefined) return;
    event.preventDefault();
    inputElement.focus();
    inputElement.select();
  }

  // The update time appears over the map: its labels keep clear of it.
  $effect(() => {
    if (UpdateTime !== null && updatedAt !== null) basemap?.controlsChanged();
  });

  /** A live file is shown, or none is: the update time follows it. */
  function onUpdated(generatedAt: UtcInstant | null): void {
    updatedAt = generatedAt;
    if (generatedAt === null || UpdateTime !== null) return;
    import('./ui/UpdateTime.svelte').then(
      (module) => {
        UpdateTime = module.default;
      },
      () => undefined,
    );
  }

  /**
   * Asks the phone where it is (the browser asks the person first, this once)
   * and glides the map to their area, which the map then keeps as its home
   * view; with that allowed, the phone opens there from then on
   * (app/nearby.ts). A position off the continental US, or none, leaves the
   * map where it is.
   */
  function locate(): void {
    if (locating || !('geolocation' in navigator)) return;
    locating = true;
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        locating = false;
        const place = { lat: coords.latitude, lon: coords.longitude };
        if (basemap === undefined) pendingNear = place;
        else basemap.showNear(place);
      },
      () => {
        locating = false;
      },
      { maximumAge: 10 * 60_000, timeout: 20_000 },
    );
  }

  function clear(): void {
    query = '';
    runSearch('');
    inputElement?.focus();
  }

  /** Moves the still from the static shell into this frame: the same node, never redrawn. */
  const adoptStill: Attachment<HTMLDivElement> = (frame) => {
    if (still !== null) frame.append(still);
  };

  onMount(() => {
    const controller = new AbortController();
    const links = createUrlStore();
    urls = links;
    // Back and Forward leave the last pick: the field no longer names what the map shows.
    const stopFollowing = links.subscribe((_state, origin) => {
      if (origin !== 'history' || pickedName === null) return;
      if (query === pickedName) {
        query = '';
        runSearch('');
      }
      pickedName = null;
    });
    const started = startMap(controller.signal, links);
    const map = started.then((parts) => parts?.basemap);
    const glow = started.then((parts) => parts?.glow ?? null);
    services = afterFirstPaint()
      .then(() => import('./app/boot'))
      .then(({ boot }) => {
        if (controller.signal.aborted) return null;
        return boot({
          links,
          map,
          glow,
          signal: controller.signal,
          show,
          // A school opens its panel: the map puts it in the middle of what the panel leaves in view.
          frame: (view, opened) => (opened?.kind === 'school' ? clearOfPanel(view) : view),
          listId: LIST_ID,
          onResults: (next) => {
            options = next;
            active = next !== null && next.length > 0 ? 0 : -1;
          },
          onUpdated,
        });
      })
      .catch(() => null);
    // Subscribed once the app's services are on their way: an open school reads through them.
    const stopSelection = links.subscribe((state) => {
      selection = state.selection;
    });
    let stopPins: () => void = () => undefined;
    void services.then((app) => {
      if (app === null || controller.signal.aborted) return;
      stopPins = app.pins.subscribe((id) => {
        pinnedId = id;
      });
    });
    return () => {
      stopFollowing();
      stopSelection();
      stopPins();
      clearTimeout(copiedTimer);
      controller.abort();
      links.destroy();
    };
  });
</script>

<svelte:window onkeydown={onShortcut} />

<main class="stage" bind:this={stageElement}>
  <div class="map" bind:this={mapElement}></div>
  <div class="frame" aria-hidden="true" bind:this={frameElement} {@attach adoptStill}></div>
  <header
    class="bar"
    bind:this={headerElement}
    onfocusout={(event) => {
      const next = event.relatedTarget;
      if (!(next instanceof Node) || headerElement?.contains(next) !== true) focused = false;
    }}
  >
    <h1 class="wordmark" data-brand>{copy.appName}</h1>
    <!-- Enter picks a result; it never reloads the page. -->
    <form
      class="search"
      class:has-query={query !== ''}
      role="search"
      onsubmit={(event) => {
        event.preventDefault();
      }}
    >
      <svg class="search-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <circle cx="7" cy="7" r="4.75" />
        <path d="M10.5 10.5l3.5 3.5" />
      </svg>
      <input
        class="search-input"
        type="search"
        name="q"
        bind:this={inputElement}
        bind:value={query}
        placeholder={copy.search.placeholder}
        aria-label={copy.search.placeholder}
        aria-keyshortcuts="/"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={listed}
        aria-controls={listed ? LIST_ID : undefined}
        aria-activedescendant={listed ? options?.[active]?.id : undefined}
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        enterkeyhint="search"
        onfocus={onFocus}
        oninput={() => {
          runSearch(query);
        }}
        onkeydown={onKeydown}
      />
      <span class="search-key" aria-hidden="true">
        <svg viewBox="0 0 12 12" focusable="false"><path d="M7.75 1.75l-3.5 8.5" /></svg>
      </span>
      {#if query !== ''}
        <button class="search-clear" type="button" aria-label={copy.search.clear} onclick={clear}>
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
          </svg>
        </button>
      {/if}
    </form>
    {#if Results !== null && expanded}
      <Results
        id={LIST_ID}
        options={options ?? []}
        {active}
        onpick={pick}
        onactive={(index) => {
          active = index;
        }}
      />
    {/if}
  </header>
  <ul class="legend" aria-label={copy.legend.label}>
    <li><span class="glyph is-closed" aria-hidden="true"></span>{copy.status.closed}</li>
    <li><span class="glyph is-delayed" aria-hidden="true"></span>{copy.status.delayed}</li>
    <li><span class="glyph is-remote" aria-hidden="true"></span>{copy.status.remote}</li>
    <li>
      <span class="glyph is-early-dismissal" aria-hidden="true"></span>{copy.status.earlyDismissal}
    </li>
  </ul>
  <button
    class="locate"
    class:is-locating={locating}
    type="button"
    aria-label={copy.map.locate}
    aria-busy={locating}
    onclick={locate}
  >
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M13.25 2.75L2.75 7.1l4.6 1.55 1.55 4.6z" />
    </svg>
  </button>
  {#if UpdateTime !== null && updatedAt !== null}
    <UpdateTime generatedAt={updatedAt} />
  {/if}
  {#if Detail !== null && schoolView !== null}
    <Detail
      view={schoolView}
      pinned={pinnedId === schoolView.id}
      {copied}
      onclose={closeSchool}
      onpin={togglePin}
      onshare={shareSchool}
      onnearby={openNearby}
      bind:element={detailElement}
    />
  {/if}
  <p class="sr-only" role="status">
    {expanded && options?.length === 0 ? copy.search.noResults : ''}
  </p>
</main>
