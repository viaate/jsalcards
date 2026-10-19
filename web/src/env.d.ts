interface ImportMetaEnv {
  /**
   * The live root this build reads live/closings.json from, such as
   * "https://live.example.org/v1/" (pwa/config.ts liveRootOf); unset, the page
   * reads its own data/.
   */
  readonly VITE_SNOWLIGHT_LIVE_ROOT?: string;
  /**
   * "1" lets the live root be plain http on this machine (localhost,
   * 127.0.0.1, [::1]): set by the e2e's build alone, never the site's.
   */
  readonly VITE_SNOWLIGHT_LIVE_LOOPBACK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
