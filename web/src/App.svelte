<script lang="ts">
  import { onMount } from 'svelte';
  import type { Attachment } from 'svelte/attachments';

  import { copy } from './copy';
  import type { Basemap } from './map/basemap';
  import { loadBasemap } from './map/basemap/load';
  import { markStep, yieldToMain } from './map/basemap/reveal';
  import { afterFirstPaint } from './shell/paint';
  import { retireStill } from './shell/still';

  interface Props {
    /** The inline still from index.html, handed over by main.ts. */
    still?: SVGSVGElement | null;
    /** Text typed into the static search field before the app started. */
    initialQuery?: string;
  }

  let { still = null, initialQuery = '' }: Props = $props();

  let mapElement = $state<HTMLDivElement>();
  let frameElement = $state<HTMLDivElement>();

  /**
   * Loads MapLibre after the first paint and hands the view over from the
   * still to the WebGL map once the map draws the same lines. If the map
   * cannot start (no WebGL), the still simply stays.
   */
  async function startMap(signal: AbortSignal): Promise<Basemap | undefined> {
    // A function, so each check reads the signal afresh after an await.
    const aborted = (): boolean => signal.aborted;
    await afterFirstPaint();
    if (aborted() || mapElement === undefined || frameElement === undefined) return;
    const container = mapElement;
    const frame = frameElement;
    let basemap: Basemap;
    try {
      const factory = await loadBasemap();
      markStep('map-loaded');
      // Evaluating MapLibre and creating the map are each sizable; keep them in separate tasks.
      await yieldToMain();
      if (aborted()) return;
      basemap = factory.create({ container, frame });
    } catch (error) {
      console.warn('Snowlight: map unavailable', error);
      return;
    }
    signal.addEventListener('abort', () => {
      basemap.destroy();
    });

    let handedOver = false;
    const handOver = (): void => {
      if (handedOver || still === null) return;
      handedOver = true;
      retireStill(still);
      markStep('map-takeover');
    };
    // Someone moving the map before it is ready must not see a frozen still on top.
    basemap.map.on('movestart', (event) => {
      if (event.originalEvent !== undefined) handOver();
    });
    await basemap.ready;
    if (!aborted()) handOver();
    return basemap;
  }

  /** Moves the still from the static shell into this frame: the same node, never redrawn. */
  const adoptStill: Attachment<HTMLDivElement> = (frame) => {
    if (still !== null) frame.append(still);
  };

  onMount(() => {
    const controller = new AbortController();
    void startMap(controller.signal);
    return () => {
      controller.abort();
    };
  });
</script>

<main class="stage">
  <div class="map" bind:this={mapElement}></div>
  <div class="frame" aria-hidden="true" bind:this={frameElement} {@attach adoptStill}></div>
  <header class="bar">
    <h1 class="wordmark">{copy.appName}</h1>
    <!-- Search itself arrives with the search engine; until then Enter must not reload the page. -->
    <form
      class="search"
      role="search"
      onsubmit={(event) => {
        event.preventDefault();
      }}
    >
      <input
        class="search-input"
        type="search"
        name="q"
        value={initialQuery}
        placeholder={copy.search.placeholder}
        aria-label={copy.search.placeholder}
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        enterkeyhint="search"
      />
    </form>
  </header>
</main>
