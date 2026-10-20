<script lang="ts">
  import { onMount } from 'svelte';

  import { ApiError } from '../../account/api';
  import { withoutSchool } from '../../account/pins';
  import type { AccountState, AccountStore, SheetView } from '../../account/session';
  import { accountCopy, accountFormat, type AccountErrorCode } from '../../copy-account';

  interface Props {
    store: AccountStore;
    view: SheetView;
    /** The school pinned on this device, marked in My schools. */
    pinnedId: string | null;
    onview: (view: SheetView) => void;
    onclose: () => void;
    /** Opens a saved school on the map. */
    onschool: (id: string) => void;
  }

  let { store, view, pinnedId, onview, onclose, onschool }: Props = $props();

  let account = $state<AccountState>({ available: false, ready: false, user: null });
  let busy = $state(false);
  let error = $state<AccountErrorCode | null>(null);
  let saved = $state<string | null>(null);
  let dialog = $state<HTMLElement>();

  // Sign up and log in.
  let name = $state('');
  let email = $state('');
  let password = $state('');
  let over13 = $state(false);
  // Settings.
  let newName = $state('');
  let newEmail = $state('');
  let emailPassword = $state('');
  let currentPassword = $state('');
  let newPassword = $state('');
  let deletePassword = $state('');

  onMount(() => {
    const stop = store.subscribe((next) => {
      account = next;
    });
    const user = store.state.user;
    newName = user?.name ?? '';
    newEmail = user?.email ?? '';
    queueMicrotask(() => dialog?.querySelector<HTMLElement>('input, button.primary')?.focus());
    return stop;
  });

  const user = $derived(account.user);
  const title = $derived(
    view === 'signup'
      ? accountCopy.sheet.signup
      : view === 'login'
        ? accountCopy.sheet.login
        : view === 'schools'
          ? accountCopy.schools.title
          : accountCopy.settings.title,
  );

  function errorCode(caught: unknown): AccountErrorCode {
    const code = caught instanceof ApiError ? caught.code : 'server';
    return code in accountCopy.errors ? (code as AccountErrorCode) : 'server';
  }

  async function run(action: () => Promise<void>, done?: string): Promise<boolean> {
    if (busy) return false;
    busy = true;
    error = null;
    saved = null;
    try {
      await action();
      if (done !== undefined) saved = done;
      return true;
    } catch (caught) {
      error = errorCode(caught);
      return false;
    } finally {
      busy = false;
    }
  }

  async function submitSignup(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (await run(() => store.signup(name, email, password, over13))) onclose();
    password = '';
  }

  async function submitLogin(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (await run(() => store.login(email, password))) onclose();
    password = '';
  }

  async function saveName(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await run(() => store.update({ name: newName }), 'name');
  }

  async function saveEmail(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await run(() => store.update({ email: newEmail, currentPassword: emailPassword }), 'email');
    emailPassword = '';
  }

  async function savePassword(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await run(() => store.update({ currentPassword, newPassword }), 'password');
    currentPassword = '';
    newPassword = '';
  }

  async function deleteAccount(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (await run(() => store.deleteAccount(deletePassword))) onclose();
    deletePassword = '';
  }

  function remove(id: string): void {
    const current = account.user;
    if (current === null) return;
    void run(() => store.setSchools(withoutSchool(current.schools, id)));
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      onclose();
      return;
    }
    // Keep Tab inside the sheet while it is open.
    if (event.key !== 'Tab' || dialog === undefined) return;
    const focusable = [
      ...dialog.querySelectorAll<HTMLElement>(
        'button, input, [href], [tabindex]:not([tabindex="-1"])',
      ),
    ].filter((el) => !el.hasAttribute('disabled'));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // Signed out on another tab, or by the API: the account views close.
  $effect(() => {
    if (account.ready && user === null && (view === 'schools' || view === 'settings')) onclose();
  });
</script>

<div class="scrim" role="presentation" onpointerdown={onclose}></div>
<div
  class="sheet"
  role="dialog"
  aria-modal="true"
  aria-labelledby="account-title"
  tabindex="-1"
  bind:this={dialog}
  onkeydown={onKeydown}
>
  <header>
    <h2 id="account-title">{title}</h2>
    <button class="close" type="button" aria-label={accountCopy.sheet.close} onclick={onclose}>
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
      </svg>
    </button>
  </header>

  {#if view === 'signup'}
    <form onsubmit={submitSignup}>
      <label>
        <span>{accountCopy.sheet.name}</span>
        <input bind:value={name} autocomplete="name" maxlength="40" required />
      </label>
      <label>
        <span>{accountCopy.sheet.email}</span>
        <input bind:value={email} type="email" autocomplete="email" maxlength="254" required />
      </label>
      <label>
        <span>{accountCopy.sheet.password}</span>
        <input
          bind:value={password}
          type="password"
          autocomplete="new-password"
          minlength="8"
          maxlength="128"
          required
          aria-describedby="password-hint"
        />
      </label>
      <small id="password-hint">{accountCopy.sheet.passwordHint}</small>
      <label class="check">
        <input bind:checked={over13} type="checkbox" required />
        <span>{accountCopy.sheet.over13}</span>
      </label>
      <p class="note">{accountCopy.sheet.ageNote}</p>
      <p class="note">{accountCopy.sheet.privacy}</p>
      {#if error !== null}<p class="error" role="alert">{accountCopy.errors[error]}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>
        {busy ? accountCopy.sheet.working : accountCopy.sheet.createAccount}
      </button>
      <button
        class="link"
        type="button"
        onclick={() => {
          onview('login');
        }}
      >
        {accountCopy.sheet.toLogin}
      </button>
    </form>
  {:else if view === 'login'}
    <form onsubmit={submitLogin}>
      <label>
        <span>{accountCopy.sheet.loginField}</span>
        <input bind:value={email} autocomplete="username" maxlength="254" required />
      </label>
      <label>
        <span>{accountCopy.sheet.password}</span>
        <input
          bind:value={password}
          type="password"
          autocomplete="current-password"
          maxlength="128"
          required
        />
      </label>
      {#if error !== null}<p class="error" role="alert">{accountCopy.errors[error]}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>
        {busy ? accountCopy.sheet.working : accountCopy.sheet.login}
      </button>
      <button
        class="link"
        type="button"
        onclick={() => {
          onview('signup');
        }}
      >
        {accountCopy.sheet.toSignup}
      </button>
    </form>
  {:else if view === 'schools' && user !== null}
    {#if user.schools.length === 0}
      <p class="note">{accountCopy.schools.empty}</p>
    {:else}
      <ul class="schools">
        {#each user.schools as school (school.id)}
          <li>
            <button
              class="school"
              type="button"
              aria-label={accountFormat.openSchool(school.name)}
              onclick={() => {
                onschool(school.id);
                onclose();
              }}
            >
              <span class="school-name">{school.name}</span>
              {#if school.id === pinnedId}<span class="tag">{accountCopy.schools.pinned}</span>{/if}
            </button>
            <button
              class="remove"
              type="button"
              aria-label={accountFormat.removeSchool(school.name)}
              disabled={busy}
              onclick={() => {
                remove(school.id);
              }}
            >
              {accountCopy.schools.remove}
            </button>
          </li>
        {/each}
      </ul>
      {#if user.schools.length >= 5}<p class="note">{accountCopy.schools.full}</p>{/if}
    {/if}
    {#if error !== null}<p class="error" role="alert">{accountCopy.errors[error]}</p>{/if}
  {:else if view === 'settings' && user !== null}
    <form onsubmit={saveName}>
      <label>
        <span>{accountCopy.settings.name}</span>
        <input bind:value={newName} autocomplete="name" maxlength="40" required />
      </label>
      <button class="secondary" type="submit" disabled={busy}>
        {saved === 'name' ? accountCopy.settings.saved : accountCopy.settings.save}
      </button>
    </form>
    {#if user.role === 'admin'}
      <p class="note">{accountCopy.settings.adminNote}</p>
    {:else}
      <form onsubmit={saveEmail}>
        <label>
          <span>{accountCopy.settings.email}</span>
          <input bind:value={newEmail} type="email" autocomplete="email" maxlength="254" required />
        </label>
        <label>
          <span>{accountCopy.settings.passwordForEmail}</span>
          <input
            bind:value={emailPassword}
            type="password"
            autocomplete="current-password"
            maxlength="128"
            required
          />
        </label>
        <button class="secondary" type="submit" disabled={busy}>
          {saved === 'email' ? accountCopy.settings.saved : accountCopy.settings.save}
        </button>
      </form>
      <form onsubmit={savePassword}>
        <label>
          <span>{accountCopy.settings.currentPassword}</span>
          <input
            bind:value={currentPassword}
            type="password"
            autocomplete="current-password"
            maxlength="128"
            required
          />
        </label>
        <label>
          <span>{accountCopy.settings.newPassword}</span>
          <input
            bind:value={newPassword}
            type="password"
            autocomplete="new-password"
            minlength="8"
            maxlength="128"
            required
          />
        </label>
        <button class="secondary" type="submit" disabled={busy}>
          {saved === 'password' ? accountCopy.settings.saved : accountCopy.settings.changePassword}
        </button>
      </form>
    {/if}
    {#if error !== null}<p class="error" role="alert">{accountCopy.errors[error]}</p>{/if}
    <p class="note">{accountCopy.settings.privacy}</p>
    {#if user.role !== 'admin'}
      <form class="danger" onsubmit={deleteAccount}>
        <h3>{accountCopy.settings.deleteTitle}</h3>
        <p class="note">{accountCopy.settings.deleteNote}</p>
        <label>
          <span>{accountCopy.sheet.password}</span>
          <input
            bind:value={deletePassword}
            type="password"
            autocomplete="current-password"
            maxlength="128"
            required
          />
        </label>
        <button class="destructive" type="submit" disabled={busy}>
          {accountCopy.settings.deleteButton}
        </button>
      </form>
    {/if}
  {/if}
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgb(0 0 0 / 0.55);
    animation: fade 160ms ease-out both;
  }

  /* Under the account control on a wide screen; a sheet from the foot of a phone's. */
  .sheet {
    position: fixed;
    top: calc(var(--inset-top) + var(--edge) + var(--bar-height) + 8px);
    right: calc(var(--inset-right) + var(--edge));
    z-index: 21;
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: 360px;
    max-height: calc(100dvh - var(--inset-top) - var(--bar-height) - 2 * var(--edge) - 16px);
    padding: 20px;
    overflow-y: auto;
    overscroll-behavior: contain;
    color: var(--text-1);
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 16px;
    outline: none;
    box-shadow:
      inset 0 1px 0 rgb(255 255 255 / 0.04),
      0 0 0 1px var(--bg),
      0 16px 40px rgb(0 0 0 / 0.6);
    animation: arrive 180ms cubic-bezier(0.2, 0.7, 0.2, 1) both;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  h2 {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }

  .close {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    color: var(--text-2);
    cursor: pointer;
    background: none;
    border: 0;
    border-radius: 50%;
  }

  .close:hover,
  .close:focus-visible {
    color: var(--text-1);
    background: var(--surface-2);
    outline: none;
  }

  .close svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
  }

  form {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  form + form {
    padding-top: 16px;
    border-top: 1px solid var(--border-1);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--text-2);
  }

  label.check {
    flex-direction: row;
    gap: 10px;
    align-items: center;
    color: var(--text-1);
  }

  input {
    height: 40px;
    padding: 0 12px;
    font: inherit;
    font-size: 15px;
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 10px;
  }

  input:focus-visible {
    border-color: var(--text-3);
    outline: 1px solid var(--text-2);
    outline-offset: 1px;
  }

  input[type='checkbox'] {
    width: 18px;
    height: 18px;
    padding: 0;
    accent-color: var(--text-1);
  }

  small,
  .note {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
  }

  .error {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--status-delayed);
  }

  button.primary,
  button.secondary,
  button.destructive {
    height: 40px;
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    border-radius: 10px;
  }

  button.primary {
    color: var(--bg);
    background: var(--text-1);
    border: 0;
  }

  button.secondary {
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
  }

  button.destructive {
    color: var(--text-1);
    background: none;
    border: 1px solid var(--border-2);
  }

  button.primary:disabled,
  button.secondary:disabled,
  button.destructive:disabled {
    cursor: default;
    opacity: 0.6;
  }

  button.link {
    align-self: center;
    padding: 4px;
    font: inherit;
    font-size: 13px;
    color: var(--text-2);
    cursor: pointer;
    background: none;
    border: 0;
  }

  button.link:hover,
  button.link:focus-visible {
    color: var(--text-1);
  }

  button:focus-visible {
    outline: 1px solid var(--text-2);
    outline-offset: 2px;
  }

  .schools {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .schools li {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .school {
    display: flex;
    flex: 1;
    gap: 8px;
    align-items: center;
    min-width: 0;
    height: 44px;
    padding: 0 10px;
    font: inherit;
    font-size: 15px;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    background: none;
    border: 0;
    border-radius: 10px;
  }

  .school:hover,
  .school:focus-visible {
    background: var(--surface-2);
  }

  .school-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tag {
    flex: none;
    padding: 2px 8px;
    font-size: 12px;
    color: var(--text-2);
    border: 1px solid var(--border-2);
    border-radius: 10px;
  }

  .remove {
    flex: none;
    height: 32px;
    padding: 0 10px;
    font: inherit;
    font-size: 13px;
    color: var(--text-2);
    cursor: pointer;
    background: none;
    border: 1px solid var(--border-2);
    border-radius: 8px;
  }

  .danger {
    padding-top: 16px;
    border-top: 1px solid var(--border-1);
  }

  @keyframes fade {
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

  @media (max-width: 719px) {
    .sheet {
      top: auto;
      right: 0;
      bottom: 0;
      left: 0;
      width: auto;
      max-height: calc(100dvh - var(--inset-top) - 24px);
      padding: 20px calc(var(--inset-right) + 16px) calc(var(--inset-bottom) + 20px)
        calc(var(--inset-left) + 16px);
      border-radius: 16px 16px 0 0;
    }

    input {
      height: 44px;
      font-size: 16px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .scrim,
    .sheet {
      animation: none;
    }
  }
</style>
