/**
 * The US mask archive (us-mask.ts) under a name that never changes, relative
 * to the site base URL: the build publishes a copy of the current mask there
 * (tools/mask-alias.ts). A page from an older build, kept by the service
 * worker, asks for the mask file its build named; once a new build has
 * replaced that file, it asks here instead (mask/feed.ts). This module
 * imports nothing, so Vite's config loader can read it.
 */
export const US_MASK_ALIAS = 'geo/us-mask.pmtiles';
