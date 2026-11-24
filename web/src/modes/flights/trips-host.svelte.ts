/**
 * Flights' trips as the panels read them (flights spec D12): the signed-in account (shared by the
 * account code, account/shared.ts), its trips, its Google state, and the calls that change them.
 * One per Flights start; it stops with the mode. Nothing is read until a panel asks (load), so
 * opening Flights asks the API for nothing.
 */
import { watchAccount, type SharedAccount } from '../../account/shared';
import { tripsCopy } from '../../copy-trips';
import { ApiError } from '../../account/api';
import {
  GOOGLE_OFF,
  createTripsClient,
  type GoogleConfig,
  type GoogleState,
  type NewTrip,
  type Trip,
  type TripChange,
  type TripsClient,
} from './trips';

export type TripsStatus = 'none' | 'signedOut' | 'loading' | 'failed' | 'ready';

export class TripsHost {
  /** No accounts on this page (no API, or it did not answer): no trips at all. */
  status = $state<TripsStatus>('none');
  trips = $state<readonly Trip[]>([]);
  google = $state<GoogleConfig>(GOOGLE_OFF);
  googleState = $state<GoogleState | null>(null);
  /** A short line after a change ("Added to your trips"), or a failure's words. */
  note = $state<string | null>(null);
  #account: SharedAccount | null = null;
  #client: TripsClient | null = null;
  #user: string | null = null;
  #wanted = false;
  #stops: (() => void)[] = [];
  /**
   * The Google state's turn (SAFE-R4-B1): every change of it (a finish, a disconnect) starts a
   * new one, and an answer read in an earlier turn is never shown. While a return from Google
   * waits to be finished, the page does not read the state at all: the finish's answer is it.
   */
  #googleTurn = 0;
  #googleHeld = false;

  constructor(signal: AbortSignal) {
    const stopAccount = watchAccount((account) => {
      this.#account = account;
      this.#follow();
    });
    this.#stops.push(stopAccount);
    signal.addEventListener(
      'abort',
      () => {
        for (const stop of this.#stops) stop();
        this.#stops = [];
      },
      { once: true },
    );
  }

  #follow(): void {
    const account = this.#account;
    this.#stops.splice(1).forEach((stop) => {
      stop();
    });
    if (account === null) {
      this.#client = null;
      this.#user = null;
      this.status = 'none';
      this.trips = [];
      return;
    }
    this.#client = createTripsClient(account.store);
    const stop = account.store.subscribe((state) => {
      const user = state.user?.id ?? null;
      if (!state.ready) return;
      if (user === this.#user && this.status !== 'none') return;
      this.#user = user;
      this.trips = [];
      this.googleState = null;
      if (user === null) this.status = 'signedOut';
      else if (this.#wanted) void this.#read();
      else this.status = 'loading';
    });
    this.#stops.push(stop);
  }

  /** Reads the trips (and whether Google is set up), once a panel needs them. */
  load(): void {
    this.#wanted = true;
    if (this.#user !== null && (this.status === 'loading' || this.status === 'failed'))
      void this.#read();
  }

  async #read(): Promise<void> {
    const client = this.#client;
    const user = this.#user;
    if (client === null || user === null) return;
    this.status = 'loading';
    try {
      const [trips, google] = await Promise.all([client.list(), client.googleConfig()]);
      if (user !== this.#user) return;
      this.trips = trips;
      this.google = google;
      this.status = 'ready';
      if (google.configured && !this.#googleHeld) await this.#readGoogle(client, user);
    } catch {
      if (user === this.#user) this.status = 'failed';
    }
  }

  async #readGoogle(client: TripsClient, user: string): Promise<void> {
    const turn = this.#googleTurn;
    const state = await client.google().catch(() => null);
    if (turn === this.#googleTurn && user === this.#user) this.googleState = state;
  }

  /** A return from Google waits: the Google state is not read until it is finished. */
  holdGoogle(): void {
    this.#googleHeld = true;
    this.#googleTurn += 1;
  }

  /**
   * Finishes a return from Google (its code and state; null: the person said no). The finish's
   * answer is the state; a refused or failed one reads it again after (the refusal can end the
   * link there was). Whether Google is now connected by this finish.
   */
  async finishGoogle(code: string | null, state: string | null): Promise<boolean> {
    const client = this.#client;
    const user = this.#user;
    this.#googleTurn += 1;
    const turn = this.#googleTurn;
    try {
      if (client === null || user === null) return false;
      if (code !== null && state !== null) {
        try {
          const answer = await client.finishGoogle(code, state);
          if (turn === this.#googleTurn && user === this.#user) this.googleState = answer;
          return true;
        } catch {
          // Read again below.
        }
      }
      if (turn === this.#googleTurn) await this.#readGoogle(client, user);
      return false;
    } finally {
      if (turn === this.#googleTurn) this.#googleHeld = false;
    }
  }

  /** The Google state a change here made (a disconnect): any read before it is not shown. */
  setGoogle(state: GoogleState | null): void {
    this.#googleTurn += 1;
    this.googleState = state;
  }

  get client(): TripsClient | null {
    return this.#client;
  }

  /** Opens the account sheet's sign-in. */
  signIn(): void {
    this.#account?.open('login');
  }

  /** The saved trip for a flight on a day, if there is one. */
  find(carrier: string, number: number, from: string, day: string): Trip | null {
    return (
      this.trips.find(
        (trip) =>
          trip.carrier === carrier &&
          trip.number === number &&
          trip.from === from &&
          trip.day === day,
      ) ?? null
    );
  }

  async save(trip: NewTrip): Promise<Trip | null> {
    const client = this.#client;
    if (client === null) return null;
    try {
      const saved = await client.add(trip);
      this.trips = [...this.trips.filter((t) => t.id !== saved.id), saved].sort(byWhen);
      this.note = tripsCopy.added;
      return saved;
    } catch (error) {
      this.note =
        error instanceof ApiError && error.code === 'too_many_trips'
          ? tripsCopy.full
          : tripsCopy.saveFailed;
      return null;
    }
  }

  async change(id: string, change: TripChange): Promise<void> {
    const client = this.#client;
    if (client === null) return;
    try {
      const saved = await client.change(id, change);
      this.trips = this.trips.map((t) => (t.id === saved.id ? saved : t));
    } catch {
      this.note = tripsCopy.saveFailed;
    }
  }

  async remove(id: string): Promise<void> {
    const client = this.#client;
    if (client === null) return;
    try {
      await client.remove(id);
      this.trips = this.trips.filter((t) => t.id !== id);
      this.note = tripsCopy.removed;
    } catch {
      this.note = tripsCopy.saveFailed;
    }
  }
}

function byWhen(a: Trip, b: Trip): number {
  return a.day.localeCompare(b.day) || a.leaves - b.leaves;
}
