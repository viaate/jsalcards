/**
 * Where the service worker keeps its note of the newest Flights alert it has shown under each tag
 * (src/pwa/push.ts, TRAV-R7-S2), and how a page clears those notes: at sign-out, account delete,
 * notifications or Flights alerts turned off, and a trip deleted (TRAV-P1-S3). Kept apart from
 * push.ts so the account and trips code can clear the notes without the worker's words.
 *
 * The notes are in IndexedDB (TRAV-P2-B1): a write reads the note and puts the new one in one
 * readwrite transaction, so it is all or nothing, and transactions on the store run in the order
 * they were made, so a late write can never land over a newer one.
 */

/** The database of the notes, and its one store: one note per tag, keyed by the tag. */
export const ALERT_DB = 'snowlight-flights-alerts';
export const ALERT_NOTES = 'notes';
/** The tag groups of one trip's alerts (push.ts flightTag). */
const GROUPS = ['risk', 'faa', 'waiver'] as const;
/** How long a page waits on the store before it goes on without it. */
const PAGE_WAIT_MS = 1000;

/** The IndexedDB parts these helpers use (tests hand a fake). */
export type AlertDb = Pick<IDBFactory, 'open' | 'deleteDatabase'>;

function pageDb(): AlertDb | null {
  try {
    return typeof indexedDB === 'undefined' ? null : indexedDB;
  } catch {
    return null;
  }
}

/**
 * Opens the notes, making the store the first time. The connection closes itself when a page
 * drops the database, so the drop is never held up; `gone` hears of it.
 */
export function openNotes(db: AlertDb, gone: () => void = () => undefined): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = db.open(ALERT_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(ALERT_NOTES))
        request.result.createObjectStore(ALERT_NOTES);
    };
    request.onsuccess = () => {
      const open = request.result;
      open.onversionchange = () => {
        gone();
        open.close();
      };
      open.onclose = gone;
      resolve(open);
    };
    request.onerror = () => {
      reject(request.error ?? new Error('The alert notes cannot be opened.'));
    };
  });
}

/** Settles when a transaction is done: it either all happened, or none of it did. */
export function finished(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => {
      resolve();
    };
    transaction.onerror = transaction.onabort = () => {
      reject(transaction.error ?? new Error('The alert notes were not changed.'));
    };
  });
}

/** Waits on `work` for at most PAGE_WAIT_MS. The work itself goes on, never dropped half done. */
async function waitOn(work: Promise<unknown>): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      work.catch(() => undefined),
      new Promise((resolve) => (timer = setTimeout(resolve, PAGE_WAIT_MS))),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/** Drops every note (a browser that keeps no storage: nothing to drop). */
export async function forgetAlerts(db: AlertDb | null = pageDb()): Promise<void> {
  try {
    if (db === null) return;
    const request = db.deleteDatabase(ALERT_DB);
    // Blocked: the worker is still writing. The drop is queued behind it and happens next.
    await waitOn(
      new Promise((resolve) => {
        request.onsuccess = request.onerror = request.onblocked = resolve;
      }),
    );
  } catch {
    // Nothing kept, or nothing that can be reached.
  }
}

/** Drops the notes of one trip's alerts. */
export async function forgetTrip(trip: string, db: AlertDb | null = pageDb()): Promise<void> {
  try {
    if (db === null) return;
    await waitOn(
      openNotes(db).then(async (open) => {
        try {
          const transaction = open.transaction(ALERT_NOTES, 'readwrite');
          const notes = transaction.objectStore(ALERT_NOTES);
          for (const group of GROUPS) notes.delete(`fl-${group}-${trip}`);
          await finished(transaction);
        } finally {
          open.close();
        }
      }),
    );
  } catch {
    // Nothing kept, or nothing that can be reached.
  }
}
