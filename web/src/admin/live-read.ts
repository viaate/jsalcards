/**
 * How the admin's pages read the live files: through the same roots as the map
 * (data/live-roots.ts), so a network that blocks the live host blocks neither.
 * The live module is the map's own, loaded when first asked here, so the first
 * script carries nothing more for it.
 */

import type { Fetch } from '../data/files';

export const adminLiveFetch: Fetch = async (input, init) =>
  (await import('../data/live')).liveFetch(input, init);
