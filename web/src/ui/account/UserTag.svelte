<script lang="ts">
  import { accountFormat } from '../../copy-account';

  interface Props {
    username: string;
    /** #0001-#9999 in sign-up order; null (no box) after #9999. */
    joinNumber: number | null;
  }

  let { username, joinNumber }: Props = $props();
</script>

<!-- A username with its join number in a small box after it, the way Discord showed them. -->
<span class="user-tag" aria-label={accountFormat.userTag(username, joinNumber)}>
  <span class="username" aria-hidden="true">{username}</span>
  {#if joinNumber !== null}
    <span class="join" aria-hidden="true">{accountFormat.joinNumber(joinNumber)}</span>
  {/if}
</span>

<style>
  .user-tag {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    min-width: 0;
    max-width: 100%;
  }

  .username {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .join {
    flex: none;
    padding: 1px 6px;
    font-family: 'Geist Mono Variable', ui-monospace, monospace;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    line-height: 16px;
    color: var(--text-2);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 6px;
  }
</style>
