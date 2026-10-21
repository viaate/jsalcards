<script lang="ts">
  import { onMount } from 'svelte';

  import type { AccountStore } from '../account/session';
  import type { Services } from '../app/boot';
  import { adminCopy } from '../copy-account';
  import { adminCall } from './call';
  import Audit from './Audit.svelte';
  import Moderation from './Moderation.svelte';
  import Overview from './Overview.svelte';
  import Statuses from './Statuses.svelte';
  import Users from './Users.svelte';

  interface Props {
    store: AccountStore;
    services: () => Promise<Services | null>;
    onclose: () => void;
  }

  let { store, services, onclose }: Props = $props();

  type Tab = 'overview' | 'statuses' | 'users' | 'moderation' | 'audit';
  const TABS: readonly Tab[] = ['overview', 'statuses', 'users', 'moderation', 'audit'];

  let tab = $state<Tab>('overview');
  let app = $state<Services | null>(null);
  let heading = $state<HTMLElement>();
  // svelte-ignore state_referenced_locally
  const call = adminCall(store);

  onMount(() => {
    void services().then((loaded) => {
      app = loaded;
    });
    heading?.focus();
  });

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && !event.defaultPrevented) {
      event.preventDefault();
      onclose();
    }
  }
</script>

<!-- The admin's view of everything: full screen over the map, its code loaded only for the admin. -->
<div
  class="admin"
  role="dialog"
  aria-modal="true"
  aria-labelledby="admin-title"
  onkeydown={onKeydown}
  tabindex="-1"
>
  <header>
    <h2 id="admin-title" tabindex="-1" bind:this={heading}>{adminCopy.title}</h2>
    <button class="back" type="button" onclick={onclose}>{adminCopy.back}</button>
  </header>
  <div class="tabs" role="tablist">
    {#each TABS as name (name)}
      <button
        type="button"
        role="tab"
        aria-selected={tab === name}
        class:is-on={tab === name}
        onclick={() => {
          tab = name;
        }}
      >
        {adminCopy.tabs[name]}
      </button>
    {/each}
  </div>
  <div class="body" role="tabpanel">
    {#if tab === 'overview'}
      <Overview {call} {app} />
    {:else if tab === 'statuses'}
      <Statuses {call} {app} />
    {:else if tab === 'users'}
      <Users {call} />
    {:else if tab === 'moderation'}
      <Moderation {call} />
    {:else}
      <Audit {call} />
    {/if}
  </div>
</div>

<style>
  .admin {
    position: fixed;
    inset: 0;
    z-index: 30;
    display: flex;
    flex-direction: column;
    padding: calc(var(--inset-top) + 20px) calc(var(--inset-right) + 24px) 0
      calc(var(--inset-left) + 24px);
    color: var(--text-1);
    background: var(--bg);
    outline: none;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    max-width: 1080px;
    width: 100%;
    margin: 0 auto;
  }

  h2 {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
    outline: none;
  }

  .back {
    height: 36px;
    padding: 0 14px;
    font: inherit;
    font-size: 14px;
    color: var(--text-1);
    cursor: pointer;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 18px;
  }

  .tabs {
    display: flex;
    gap: 4px;
    max-width: 1080px;
    width: 100%;
    margin: 16px auto 0;
    overflow-x: auto;
    border-bottom: 1px solid var(--border-1);
  }

  .tabs button {
    flex: none;
    height: 40px;
    padding: 0 14px;
    font: inherit;
    font-size: 14px;
    color: var(--text-2);
    cursor: pointer;
    background: none;
    border: 0;
    border-bottom: 2px solid transparent;
  }

  .tabs button.is-on {
    color: var(--text-1);
    border-bottom-color: var(--text-1);
  }

  .body {
    flex: 1;
    max-width: 1080px;
    width: 100%;
    margin: 0 auto;
    padding: 20px 0 calc(var(--inset-bottom) + 32px);
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  button:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  /* What the sections share. */
  .admin :global(section) {
    margin: 0 0 28px;
  }

  .admin :global(h3) {
    margin: 0 0 12px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-2);
    letter-spacing: 0.01em;
  }

  .admin :global(.tiles) {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 8px;
  }

  .admin :global(.tile) {
    padding: 12px 14px;
    background: var(--surface-1);
    border: 1px solid var(--border-1);
    border-radius: 12px;
  }

  .admin :global(.tile .value) {
    display: block;
    font-size: 22px;
    font-weight: 600;
  }

  .admin :global(.tile .label) {
    display: block;
    margin-top: 4px;
    font-size: 12px;
    color: var(--text-2);
  }

  .admin :global(table) {
    width: 100%;
    font-size: 13px;
    border-collapse: collapse;
  }

  .admin :global(th),
  .admin :global(td) {
    padding: 8px 10px 8px 0;
    text-align: left;
    vertical-align: top;
    border-bottom: 1px solid var(--border-1);
  }

  .admin :global(th) {
    font-weight: 500;
    color: var(--text-2);
  }

  .admin :global(.scroll) {
    overflow-x: auto;
  }

  .admin :global(.muted) {
    color: var(--text-2);
  }

  .admin :global(.error) {
    color: var(--status-delayed);
  }

  .admin :global(input),
  .admin :global(select) {
    height: 38px;
    padding: 0 10px;
    font: inherit;
    font-size: 14px;
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 8px;
  }

  .admin :global(.button) {
    height: 34px;
    padding: 0 12px;
    font: inherit;
    font-size: 13px;
    color: var(--text-1);
    cursor: pointer;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 8px;
  }

  .admin :global(.button.primary) {
    font-weight: 600;
    color: var(--bg);
    background: var(--text-1);
    border-color: var(--text-1);
  }

  .admin :global(.button:disabled) {
    cursor: default;
    opacity: 0.6;
  }

  .admin :global(a) {
    color: var(--text-1);
  }

  @media (max-width: 719px) {
    .admin {
      padding: calc(var(--inset-top) + 16px) calc(var(--inset-right) + 16px) 0
        calc(var(--inset-left) + 16px);
    }
  }
</style>
