/**
 * Where a phone opens: over its viewer's own area when they have already let
 * the site know where they are, and on the whole country otherwise.
 *
 * The site never asks where anyone is on load (browsers and audits count
 * that against a site): it asks when "Show my area" is tapped, and from then
 * on the phone opens over that area. On load the page only reads whether it
 * may know (the Permissions API, which asks nothing), and where it may, reads
 * the phone's position roughly, taking a recent one it already has. A
 * position that is slow to come, or none, opens the whole country, and so does
 * one off the continental US (the map's to judge: limits.ts viewLimits). A
 * link, or a pinned school, opens as it always does.
 */
import type { Place } from '../map/basemap/limits';

/** How long the page waits for the phone to say where it is before it opens on the country, in milliseconds. */
export const NEARBY_WAIT_MS = 1500;

/** How old a position the phone already has can be and still be used, in milliseconds. */
export const NEARBY_MAX_AGE_MS = 30 * 60_000;

/** The custom property index.html sets to "nearby" on a phone, the screens that open near their viewer. */
export const HOME_VIEW_PROPERTY = '--home-view';

/** The parts of `navigator` read here, so tests can hand in their own. */
export type Locator = Partial<Pick<Navigator, 'permissions' | 'geolocation'>>;

/** Whether this screen opens near its viewer (a phone, held either way), as the page's style says. */
export function opensNearby(element: Element): boolean {
  return getComputedStyle(element).getPropertyValue(HOME_VIEW_PROPERTY).trim() === 'nearby';
}

/**
 * Where the viewer is, when they have already let the site know: never asks.
 * Null when they have not (or the browser cannot say whether they have), or
 * when the position fails or takes longer than `wait`.
 */
export async function grantedPlace(
  locator: Locator = navigator,
  wait: number = NEARBY_WAIT_MS,
): Promise<Place | null> {
  const { permissions, geolocation } = locator;
  if (permissions === undefined || geolocation === undefined) return null;
  let state: PermissionState;
  try {
    ({ state } = await permissions.query({ name: 'geolocation' }));
  } catch {
    return null;
  }
  if (state !== 'granted') return null;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      resolve(null);
    }, wait);
    const done = (place: Place | null): void => {
      clearTimeout(timer);
      resolve(place);
    };
    try {
      geolocation.getCurrentPosition(
        ({ coords }) => {
          done({ lat: coords.latitude, lon: coords.longitude });
        },
        () => {
          done(null);
        },
        { enableHighAccuracy: false, maximumAge: NEARBY_MAX_AGE_MS, timeout: wait },
      );
    } catch {
      done(null);
    }
  });
}
