<script lang="ts">
  import { onMount } from 'svelte';

  import { accountFormat, adminCopy } from '../copy-account';
  import type { AdminCall, AuditEntry } from './call';

  interface Props {
    call: AdminCall;
  }

  let { call }: Props = $props();

  let entries = $state<AuditEntry[] | null>(null);
  let failed = $state(false);

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
              <td>{entry.target ?? ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>
