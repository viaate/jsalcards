<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import type { Component } from 'svelte';
  import type { Attachment } from 'svelte/attachments';

  import type { SearchOption, Services, Target } from './app/boot';
  import { copy } from './copy';
  import type { Basemap } from './map/basemap';
  import { loadBasemap } from './map/basemap/load';
  import type { Glow } from './map/glow-mount';
  import { markStep, yieldToMain } from './map/basemap/reveal';
  import { afterFirstPaint } from './shell/paint';
  import { retireStill } from './shell/still';
  import { createUrlStore } from './state/url-store';
  import type { UrlStore } from './state/url-store';
  import type { UtcInstant } from './types/generated';

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

  let { still = null, initialQuery = '' }: Props = $props();

  const LIST_ID = 'search-results';

  let mapElement = $state<HTMLDivElement>();
  let frameElement = $state<HTMLDivElement>();
  let inputElement = $state<HTMLInputElement>();
  let headerElement = $state<HTMLElement>();

  let query = $state(untrack(() => initialQuery));
  /** The newest text's results, or null when there are none to show. */
  let options = $state<readonly SearchOption[] | null>(null);
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

  const expanded = $derived(
    focused && !dismissed && Results !== null && options !== null && query.trim() !== '',
  );
  const listed = $derived(expanded && options !== null && options.length > 0);

  let basemap: Basemap | undefined;
  /** Where to go once the map exists, for a result picked before it did. */
  let pendingTarget: Target | null = null;
  /** The rest of the app (search, data, glow, offline), loaded after the first paint. */
  let services: Promise<Services | null> = Promise.resolve(null);

  /** The map, once its first frame is up, and the glow layer on it (null when it could not load). */
  interface MapParts {
    basemap: Basemap;
    glow: Glow | null;
  }

  /**
   * Loads MapLibre after the first paint and hands the view over from the
   * still to the WebGL map once the map draws the same lines. If the map
   * cannot start (no WebGL), the still simply stays. A link's view opens at
   * the nearest view the map allows on this screen. The glow layer's code
   * loads alongside MapLibre's, and the layer goes on with the map's style,
   * so it never makes the map draw its first frames again.
   */
  async function startMap(signal: AbortSignal, links: UrlStore): Promise<MapParts | undefined> {
    // A function, so each check reads the signal afresh after an await.
    const aborted = (): boolean => signal.aborted;
    await afterFirstPaint();
    if (aborted() || mapElement === undefined || frameElement === undefined) return;
    const container = mapElement;
    const frame = frameElement;
    let map: Basemap;
    let glow: Glow | null = null;
    try {
      const [factory, glowCode] = await Promise.all([
        loadBasemap(),
        import('./map/glow-mount').catch(() => null),
      ]);
      markStep('map-loaded');
      // Evaluating MapLibre and creating the map are each sizable; keep them in separate tasks.
      await yieldToMain();
      if (aborted()) return;
      map = factory.create({ container, frame, view: links.state.view });
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
    followLinks(map, links, signal);
    if (pendingTarget !== null) show(pendingTarget);

    let handedOver = false;
    const handOver = (): void => {
      if (handedOver || still === null) return;
      handedOver = true;
      retireStill(still);
      markStep('map-takeover');
    };
    // Someone moving the map before it is ready must not see a frozen still on top.
    map.map.on('movestart', (event) => {
      if (event.originalEvent !== undefined) handOver();
    });
    map.map.on('wheel', handOver);
    await map.ready;
    if (!aborted()) handOver();
    return { basemap: map, glow };
  }

  /**
   * Keeps the address bar on the view the map shows (none at the national
   * view), and moves the map when Back or Forward brings back another view.
   */
  function followLinks(map: Basemap, links: UrlStore, signal: AbortSignal): void {
    const record = (): void => {
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
    inputElement?.blur();
    void services.then((app) => {
      app?.pick(option.hit);
    });
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
          active = -1;
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
          listId: LIST_ID,
          onResults: (next) => {
            options = next;
            active = -1;
          },
          onUpdated,
        });
      })
      .catch(() => null);
    return () => {
      stopFollowing();
      controller.abort();
      links.destroy();
    };
  });
</script>

<svelte:window onkeydown={onShortcut} />

<main class="stage">
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
  {#if UpdateTime !== null && updatedAt !== null}
    <UpdateTime generatedAt={updatedAt} />
  {/if}
  <p class="sr-only" role="status">
    {expanded && options?.length === 0 ? copy.search.noResults : ''}
  </p>
</main>
