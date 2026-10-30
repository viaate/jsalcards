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
  /**
   * The accounts API's root, such as "https://snowlight-api.example.workers.dev"
   * (account/config.ts apiRoot); unset or empty, the page has no account controls.
   */
  readonly VITE_API_ROOT?: string;
  /** "1" lets the API root be plain http on this machine: a local test build alone. */
  readonly VITE_API_LOOPBACK?: string;
  /** "owner/repo" the site is built from, for the admin view's run list (admin/overview.ts). */
  readonly VITE_GITHUB_REPO?: string;
  /**
   * Themes built but not yet released (theme/themes.ts THEMES_UNRELEASED) that
   * this build may use, comma-separated, such as "snowball": set only for the
   * owner's screenshots and the e2e's own build, never the site's.
   */
  readonly VITE_THEMES_PREVIEW?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
