/** The admin view's calls to the accounts API, with the admin's session. */

import { ApiError } from '../account/api';
import type { AccountStore } from '../account/session';
import { adminCopy } from '../copy-account';

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
  readonly username: string | null;
  readonly join_number: number | null;
  /** The admin renamed it and it has not picked a new one yet. */
  readonly rename_required: boolean;
}

/** POST /v1/admin/users/:id/rename's answer. */
export interface RenameResult {
  readonly id: string;
  readonly username: string;
  /** The word the old name's letters became for everyone, or null. */
  readonly blocked: { readonly term: string; readonly kind: string } | null;
  /** Why no word was added though asked: too short, or 50 words of that kind. */
  readonly block_problem: 'too_short' | 'too_many_terms' | null;
}

/** The note after a rename: what happened to the old name's word (null when it was not asked for). */
export function renameNoteFor(result: RenameResult | null): string | null {
  if (result === null) return null;
  if (result.blocked !== null) return adminCopy.users.renameBlocked;
  if (result.block_problem === 'too_short') return adminCopy.users.renameTooShort;
  if (result.block_problem === 'too_many_terms') return adminCopy.users.renameFull;
  return null;
}

export interface AuditEntry {
  readonly id: number;
  readonly at: string;
  readonly actor: string | null;
  readonly action: string;
  /** A user id, a status key, "deleted user", or null. */
  readonly target: string | null;
  /** The account the target names, as it is now; null once deleted. */
  readonly target_user: {
    readonly username: string | null;
    readonly join_number: number | null;
  } | null;
  readonly detail: Readonly<Record<string, unknown>> | null;
}

/** The most words the admin may keep of each kind (the Worker's MAX_ADMIN_TERMS, api/src/usernames/check.ts). */
export const MAX_TERMS = 50;

export interface ModerationTerm {
  readonly term: string;
  readonly kind: 'substring' | 'token' | 'allow' | 'raw';
  readonly added_at: string;
}

export interface ScanMatch {
  readonly id: string;
  readonly username: string;
  readonly join_number: number | null;
  readonly term: string;
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
  /** Networks (IPv4 /24, IPv6 /64) with 5 or more sign-ups in one UTC day in the last week. */
  readonly busy_networks?: readonly {
    readonly network: string;
    readonly day: string;
    readonly count: number;
  }[];
}
