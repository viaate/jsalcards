<script lang="ts">
  import { onMount } from 'svelte';

  import { accountCopy, accountFormat } from '../../copy-account';
  import type { AccountState, AccountStore, SheetView } from '../../account/session';

  interface Props {
    store: AccountStore;
    /** Opens the sheet on one of its views. */
    onopen: (view: SheetView) => void;
    /** Opens the admin view. */
    onadmin: () => void;
  }

  let { store, onopen, onadmin }: Props = $props();

  let account = $state<AccountState>({ available: false, ready: false, user: null });
  let open = $state(false);
  let root = $state<HTMLElement>();
  let button = $state<HTMLButtonElement>();
  let menu = $state<HTMLElement>();

  onMount(() => store.subscribe((next) => (account = next)));

  const user = $derived(account.user);
  const first = $derived(user === null ? '' : accountFormat.firstName(user.name));
  const initial = $derived.by(() => {
    const code = first.codePointAt(0);
    return code === undefined ? '' : String.fromCodePoint(code).toUpperCase();
  });

  function toggle(): void {
    if (user === null) {
      onopen('login');
      return;
    }
    open = !open;
    if (open) queueMicrotask(() => menu?.querySelector<HTMLElement>('[role="menuitem"]')?.focus());
  }

  function choose(action: () => void): void {
    open = false;
    button?.focus();
    action();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (!open) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      open = false;
      button?.focus();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const items = [...(menu?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    items[(at + step + items.length) % items.length]?.focus();
    event.preventDefault();
  }

  function onPointerDown(event: PointerEvent): void {
    if (open && event.target instanceof Node && root?.contains(event.target) !== true) open = false;
  }
</script>

<svelte:window onpointerdown={onPointerDown} />

<!--
  The account control at the right end of the strip. Signed out it reads
  "Sign up or log in" (a person icon on a phone); signed in, the first name
  (its initial on a phone), opening a small menu.
-->
<div class="account" bind:this={root} onkeydown={onKeydown} role="presentation">
  <button
    class="account-button"
    class:is-user={user !== null}
    type="button"
    bind:this={button}
    aria-label={user === null ? accountCopy.control.signedOut : accountFormat.menuLabel(user.name)}
    aria-haspopup={user === null ? 'dialog' : 'menu'}
    aria-expanded={user === null ? undefined : open}
    onclick={toggle}
  >
    {#if user === null}
      <svg class="person" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <circle cx="8" cy="5.5" r="2.75" />
        <path d="M2.75 14c0.6-2.9 2.75-4.5 5.25-4.5s4.65 1.6 5.25 4.5" />
      </svg>
      <span class="label">{accountCopy.control.signedOut}</span>
    {:else}
      <span class="initial" aria-hidden="true">{initial}</span>
      <span class="label">{first}</span>
    {/if}
  </button>
  {#if open && user !== null}
    <div class="account-menu" role="menu" bind:this={menu}>
      <button
        type="button"
        role="menuitem"
        onclick={() => {
          choose(() => {
            onopen('schools');
          });
        }}
      >
        {accountCopy.menu.mySchools}
      </button>
      <button
        type="button"
        role="menuitem"
        onclick={() => {
          choose(() => {
            onopen('settings');
          });
        }}
      >
        {accountCopy.menu.settings}
      </button>
      {#if user.role === 'admin'}
        <button
          type="button"
          role="menuitem"
          onclick={() => {
            choose(onadmin);
          }}
        >
          {accountCopy.menu.admin}
        </button>
      {/if}
      <button
        type="button"
        role="menuitem"
        onclick={() => {
          choose(() => void store.logout());
        }}
      >
        {accountCopy.menu.logout}
      </button>
    </div>
  {/if}
</div>

<style>
  /*
    In the strip's last column, at its right end, in the room index.html keeps
    for it (--account-room, only in a build with an API root), so the update
    time sits left of it from the first paint and nothing moves when it
    appears. It fades in once the API has answered.
  */
  .account {
    position: relative;
    grid-row: 1;
    grid-column: 3;
    justify-self: end;
    display: flex;
    align-items: center;
    max-width: var(--account-width);
    height: var(--bar-height);
    animation: appear 240ms ease-out both;
  }

  .account-button {
    display: flex;
    gap: 8px;
    align-items: center;
    max-width: 100%;
    height: 36px;
    margin: 0;
    padding: 0 14px 0 10px;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    line-height: 16px;
    color: var(--text-1);
    cursor: pointer;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 18px;
    box-shadow:
      inset 0 1px 0 rgb(255 255 255 / 0.07),
      0 0 0 1px var(--bg),
      0 8px 24px rgb(0 0 0 / 0.6);
    transition: border-color 120ms linear;
  }

  .account-button:hover,
  .account-button[aria-expanded='true'] {
    border-color: var(--text-3);
  }

  .account-button:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  .label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .person {
    flex: none;
    width: 16px;
    height: 16px;
    fill: none;
    stroke: var(--text-2);
    stroke-width: 1.25;
    stroke-linecap: round;
  }

  .initial {
    display: grid;
    flex: none;
    place-items: center;
    width: 20px;
    height: 20px;
    font-size: 11px;
    font-weight: 600;
    color: var(--bg);
    background: var(--text-1);
    border-radius: 50%;
  }

  .account-menu {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 3;
    display: flex;
    flex-direction: column;
    min-width: 176px;
    padding: 6px;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 14px;
    box-shadow:
      inset 0 1px 0 rgb(255 255 255 / 0.04),
      0 0 0 1px var(--bg),
      0 16px 40px rgb(0 0 0 / 0.6);
    animation: arrive 160ms cubic-bezier(0.2, 0.7, 0.2, 1) both;
  }

  .account-menu button {
    height: 36px;
    padding: 0 10px;
    font: inherit;
    font-size: 14px;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    background: none;
    border: 0;
    border-radius: 8px;
  }

  .account-menu button:hover,
  .account-menu button:focus-visible {
    background: var(--surface-2);
    outline: none;
  }

  @keyframes appear {
    from {
      opacity: 0;
    }
  }

  @keyframes arrive {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }

  /* A phone: a round button on the wordmark's line, just before the menu's. */
  @media (max-width: 719px) {
    .account {
      grid-column: 1;
      height: var(--brand-line);
      margin-right: calc(var(--menu-size) + 8px);
    }

    .account-button {
      justify-content: center;
      width: var(--menu-size);
      height: var(--menu-size);
      padding: 0;
      border-radius: 50%;
    }

    .account-button::after {
      position: absolute;
      inset: -4px;
      content: '';
    }

    .label {
      display: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .account,
    .account-menu {
      animation: none;
    }
  }
</style>
