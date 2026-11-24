/**
 * The account, as another mode reads it (flights spec D3: one account serves both modes). The
 * account code (account/boot.ts) shares its store here once it has started, and the account
 * control shares how to open the account sheet; Flights' trips read both. Loaded only with the
 * account code and the modes, never in the page's first script. Nothing here is kept on the
 * device.
 */
import type { AccountStore, SheetView } from './session';

export interface SharedAccount {
  readonly store: AccountStore;
  /** Opens the account sheet on a view (sign in, settings), as the account button does. */
  readonly open: (view: SheetView) => void;
}

let store: AccountStore | null = null;
let open: ((view: SheetView) => void) | null = null;
const listeners = new Set<(account: SharedAccount | null) => void>();

function current(): SharedAccount | null {
  return store === null || open === null ? null : { store, open };
}

function tell(): void {
  const account = current();
  for (const listener of listeners) listener(account);
}

/** The account code's store, once started (null: no accounts on this page). */
export function shareStore(next: AccountStore | null): void {
  store = next;
  tell();
}

/** The account control's opener, while it shows. */
export function shareOpener(next: ((view: SheetView) => void) | null): void {
  open = next;
  tell();
}

/** Hears the account now and whenever it comes or goes; returns the stop. */
export function watchAccount(listener: (account: SharedAccount | null) => void): () => void {
  listeners.add(listener);
  listener(current());
  return () => {
    listeners.delete(listener);
  };
}
