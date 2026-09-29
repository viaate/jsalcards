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
  SelectOptions,
  ShareOptions,
  StateOrigin,
  UrlStateListener,
  UrlStore,
  UrlStoreOptions,
} from './url-store';
export { PIN_KEY, readPin } from './pin';
export { createPinStore, writePin } from './pin-store';
export type { PinListener, PinStore, PinStoreOptions } from './pin-store';
export { createConnectivity, parseInstant, updateLine, updateState } from './freshness';
export type { Connectivity, UpdateLineInput, UpdateState } from './freshness';
