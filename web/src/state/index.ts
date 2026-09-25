/**
 * App state that outlives a page view: what the address bar holds (share
 * links), the pinned school, and how fresh the data on screen is.
 */

export {
  isDistrictId,
  isSchoolId,
  isZipCode,
  parseDistrictId,
  parseSchoolId,
  parseZipCode,
} from './ids';
export {
  EMPTY_STATE,
  PARAMS,
  VIEW_LIMITS,
  formatView,
  mergeHref,
  parseUrlState,
  parseView,
  roundView,
  sameSelection,
  sameState,
  sameView,
  shareHref,
} from './url';
export type { Selection, SelectionKind, UrlState, View } from './url';
export { createUrlStore } from './url-store';
export type {
  ShareOptions,
  StateOrigin,
  UrlStateListener,
  UrlStore,
  UrlStoreOptions,
} from './url-store';
export { PIN_KEY, createPinStore, readPin, writePin } from './pin';
export type { PinListener, PinStore, PinStoreOptions } from './pin';
export { createConnectivity, parseInstant, updateLine } from './freshness';
export type { Connectivity, UpdateLineInput } from './freshness';
