<script lang="ts">
  import { onMount } from 'svelte';

  import { accountFormat, adminCopy } from '../copy-account';
  import UserTag from '../ui/account/UserTag.svelte';
  import type { AdminCall, AuditEntry } from './call';

  interface Props {
    call: AdminCall;
  }

  let { call }: Props = $props();

  let entries = $state<AuditEntry[] | null>(null);
  let failed = $state(false);

  /** The username and number an entry's detail kept, for an account deleted since. */
  function kept(entry: AuditEntry): { username: string; join: number | null } | null {
    const username = entry.detail?.username;
    const join = entry.detail?.join_number;
    return typeof username === 'string'
      ? { username, join: typeof join === 'number' ? join : null }
      : null;
  }

  /** A word added to or removed from the lists. */
  function term(entry: AuditEntry): string {
    const word = entry.detail?.term;
    return typeof word === 'string' ? word : '';
  }

  const ACCOUNT_ACTIONS = new Set([
    'reset_password',
    'disable_user',
    'enable_user',
    'delete_user',
    'rename_user',
  ]);

  onMount(() => {
    call<{ entries: AuditEntry[] }>('GET', '/v1/admin/audit').then(
      (body) => {
        entries = body.entries;
      },
      () => {
        failed = true;
        entries = [];
      },
    );
  });
</script>

<section>
  {#if failed}<p class="error" role="alert">{adminCopy.errors.failed}</p>{/if}
  {#if entries === null}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if entries.length === 0}
    <p class="muted">{adminCopy.audit.none}</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>{adminCopy.audit.when}</th>
            <th>{adminCopy.audit.who}</th>
            <th>{adminCopy.audit.what}</th>
            <th>{adminCopy.audit.target}</th>
          </tr>
        </thead>
        <tbody>
          {#each entries as entry (entry.id)}
            <tr>
              <td class="muted">{accountFormat.when(entry.at)}</td>
              <td>{entry.actor ?? ''}</td>
              <td>{accountFormat.action(entry.action)}</td>
              <td>
                {#if entry.target_user !== null && entry.target_user.username !== null}
                  <UserTag
                    username={entry.target_user.username}
                    joinNumber={entry.target_user.join_number}
                  />
                {:else if ACCOUNT_ACTIONS.has(entry.action) || entry.target === 'deleted user'}
                  {@const was = kept(entry)}
                  <span class="muted">{adminCopy.audit.deletedUser}</span>
                  {#if was !== null}<UserTag username={was.username} joinNumber={was.join} />{/if}
                {:else if entry.action === 'add_term' || entry.action === 'remove_term'}
                  {term(entry)}
                {:else}
                  {entry.target ?? ''}
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>
