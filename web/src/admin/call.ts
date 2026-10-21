/** The admin view's calls to the accounts API, with the admin's session. */

import { ApiError } from '../account/api';
import type { AccountStore } from '../account/session';

export type AdminCall = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** Calls with the session; a 401 signs the page out (the view then closes). */
export function adminCall(store: AccountStore): AdminCall {
  return async <T>(method: string, path: string, body?: unknown): Promise<T> => {
    try {
      return await store.api.call<T>(method, path, body, store.token());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) store.signedOut();
      throw error;
    }
  };
}

export interface ManualStatus {
  readonly key: string;
  readonly scope: 'district' | 'school';
  readonly id: string;
  readonly status: 'closed' | 'delayed' | 'early_dismissal' | 'open';
  readonly minutes: number | null;
  readonly at_local_time: string | null;
  /** Its school-local days (YYYY-MM-DD), ascending: those not yet over while it is active. */
  readonly days: readonly string[];
  /** The zone the days are in; null for one set before days were stored. */
  readonly time_zone: string | null;
  readonly note: string | null;
  readonly set_at: string;
  readonly expires_at: string;
  readonly set_by: string | null;
  readonly active: boolean;
}

export interface AdminUser {
  readonly id: string;
  readonly name: string;
  readonly email: string | null;
  readonly role: 'user' | 'admin';
  readonly created_at: string;
  readonly last_login_at: string | null;
  readonly schools: number;
  readonly disabled: boolean;
}

export interface AuditEntry {
  readonly id: number;
  readonly at: string;
  readonly actor: string | null;
  readonly action: string;
  readonly target: string | null;
}

export interface Summary {
  readonly accounts: {
    readonly total: number;
    readonly new_day: number;
    readonly new_week: number;
    readonly disabled: number;
    readonly active_week: number;
  };
  readonly overrides_active: number;
}
