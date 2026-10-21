<script lang="ts">
  import { onMount } from 'svelte';

  import { ApiError } from '../../account/api';
  import { normalizeLogin } from '../../account/key';
  import { withoutSchool } from '../../account/pins';
  import type { AccountState, AccountStore, SheetView } from '../../account/session';
  import { accountCopy, accountFormat, type AccountErrorCode } from '../../copy-account';
  import { followKeyboard } from './keyboard';
  import NotifySettings from './NotifySettings.svelte';
  import UsernameField from './UsernameField.svelte';
  import UserTag from './UserTag.svelte';

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
  // Username, on sign up and on the username view.
  let username = $state('');
  // Settings.
  let newName = $state('');
  let newEmail = $state('');
  let emailPassword = $state('');
  let currentPassword = $state('');
  let newPassword = $state('');
  let deletePassword = $state('');
  /** Settings' own views: the privacy text, and the password and delete forms opened from their rows. */
  let privacyOpen = $state(false);
  let passwordOpen = $state(false);
  let deleteOpen = $state(false);

  onMount(() => {
    const stop = store.subscribe((next) => {
      account = next;
    });
    const user = store.state.user;
    newName = user?.name ?? '';
    newEmail = user?.email ?? '';
    queueMicrotask(() => dialog?.querySelector<HTMLElement>('input, button.primary')?.focus());
    // The sheet and the focused field stay above an on-screen keyboard (keyboard.ts).
    const unfollow = dialog === undefined ? () => undefined : followKeyboard(dialog);
    return () => {
      stop();
      unfollow();
    };
  });

  const user = $derived(account.user);
  const title = $derived(
    view === 'signup'
      ? accountCopy.sheet.signup
      : view === 'login'
        ? accountCopy.sheet.login
        : view === 'schools'
          ? accountCopy.schools.title
          : view === 'username'
            ? account.user?.renamed === true
              ? accountCopy.username.renamedTitle
              : accountCopy.username.title
            : privacyOpen
              ? accountCopy.settings.privacyTitle
              : accountCopy.settings.title,
  );
  /** The email field differs from the account's: its password row and Save show. */
  const emailEdited = $derived(
    user !== null && normalizeLogin(newEmail) !== normalizeLogin(user.email ?? ''),
  );
  /** The username view cannot be left except by picking one or logging out. */
  const mustPick = $derived(view === 'username');

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
    if (await run(() => store.signup(name, email, username, password, over13))) onclose();
    password = '';
  }

  async function submitUsername(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (await run(() => store.pickUsername(username, password))) onclose();
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
    if (await run(() => store.update({ currentPassword, newPassword }), 'password'))
      passwordOpen = false;
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

  /** Opens or leaves the privacy text, and puts focus where the person goes next. */
  function showPrivacy(open: boolean): void {
    privacyOpen = open;
    queueMicrotask(() =>
      dialog?.querySelector<HTMLElement>(open ? 'button.back' : 'button.privacy')?.focus(),
    );
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      if (privacyOpen) showPrivacy(false);
      else if (!mustPick) onclose();
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
    if (
      account.ready &&
      user === null &&
      (view === 'schools' || view === 'settings' || view === 'username')
    )
      onclose();
    // Picked: the username view has done its job.
    if (view === 'username' && user !== null && !user.username_required) onclose();
  });
</script>

<div
  class="scrim"
  role="presentation"
  onpointerdown={() => {
    if (!mustPick) onclose();
  }}
></div>
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
    <div class="title">
      {#if privacyOpen}
        <button
          class="back"
          type="button"
          aria-label={accountCopy.settings.back}
          onclick={() => {
            showPrivacy(false);
          }}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M10 3.5L5.5 8l4.5 4.5" />
          </svg>
        </button>
      {/if}
      <h2 id="account-title">{title}</h2>
    </div>
    {#if !mustPick}
      <button class="close" type="button" aria-label={accountCopy.sheet.close} onclick={onclose}>
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
        </svg>
      </button>
    {/if}
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
      <UsernameField {store} bind:value={username} />
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
        <input
          bind:value={email}
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          maxlength="254"
          required
        />
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
  {:else if view === 'username' && user !== null}
    <form onsubmit={submitUsername}>
      <p class="note">{user.renamed ? accountCopy.username.renamed : accountCopy.username.intro}</p>
      <UsernameField {store} bind:value={username} />
      {#if user.needs_rekey}
        <label>
          <span>{accountCopy.sheet.password}</span>
          <input
            bind:value={password}
            type="password"
            autocomplete="current-password"
            maxlength="128"
            required
            aria-describedby="rekey-note"
          />
        </label>
        <small id="rekey-note">{accountCopy.username.passwordNote}</small>
      {/if}
      {#if error !== null}<p class="error" role="alert">{accountCopy.errors[error]}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>
        {busy ? accountCopy.sheet.working : accountCopy.username.save}
      </button>
      <button
        class="link"
        type="button"
        onclick={() => {
          void store.logout();
        }}
      >
        {accountCopy.username.logout}
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
  {:else if view === 'settings' && user !== null && privacyOpen}
    <p class="prose">{accountCopy.settings.privacy}</p>
  {:else if view === 'settings' && user !== null}
    <div class="group">
      {#if user.username !== null}
        <div class="row">
          <span class="label">{accountCopy.settings.username}</span>
          <span class="value"
            ><UserTag username={user.username} joinNumber={user.join_number} /></span
          >
        </div>
      {/if}
      <form class="row" onsubmit={saveName}>
        <label class="field">
          <span class="label">{accountCopy.settings.name}</span>
          <input bind:value={newName} autocomplete="name" maxlength="40" required />
        </label>
        {#if newName.trim() !== user.name}
          <button class="save" type="submit" disabled={busy}>{accountCopy.settings.save}</button>
        {:else if saved === 'name'}
          <span class="done">{accountCopy.settings.saved}</span>
        {/if}
      </form>
    </div>
    {#if user.role === 'admin'}
      <p class="note">{accountCopy.settings.adminNote}</p>
    {:else}
      <div class="group">
        <form onsubmit={saveEmail}>
          <div class="row">
            <label class="field">
              <span class="label">{accountCopy.settings.email}</span>
              <input
                bind:value={newEmail}
                type="email"
                autocomplete="email"
                maxlength="254"
                required
              />
            </label>
            {#if !emailEdited && saved === 'email'}
              <span class="done">{accountCopy.settings.saved}</span>
            {/if}
          </div>
          {#if emailEdited}
            <div class="row">
              <label class="field">
                <span class="label dim">{accountCopy.settings.password}</span>
                <input
                  bind:value={emailPassword}
                  type="password"
                  autocomplete="current-password"
                  maxlength="128"
                  required
                />
              </label>
              {#if emailPassword !== ''}
                <button class="save" type="submit" disabled={busy}
                  >{accountCopy.settings.save}</button
                >
              {/if}
            </div>
          {/if}
        </form>
        <button
          class="row nav"
          class:open={passwordOpen}
          type="button"
          aria-expanded={passwordOpen}
          aria-controls="change-password"
          onclick={() => {
            passwordOpen = !passwordOpen;
          }}
        >
          <span class="label">{accountCopy.settings.password}</span>
          {#if !passwordOpen && saved === 'password'}
            <span class="done">{accountCopy.settings.saved}</span>
          {/if}
          <svg class="chevron" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M6 3.5l4.5 4.5L6 12.5" />
          </svg>
        </button>
        {#if passwordOpen}
          <form id="change-password" onsubmit={savePassword}>
            <label class="row field">
              <span class="label dim">{accountCopy.settings.currentPassword}</span>
              <input
                bind:value={currentPassword}
                type="password"
                autocomplete="current-password"
                maxlength="128"
                required
              />
            </label>
            <div class="row">
              <label class="field">
                <span class="label dim">{accountCopy.settings.newPassword}</span>
                <input
                  bind:value={newPassword}
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                  maxlength="128"
                  required
                />
              </label>
              {#if newPassword !== ''}
                <button class="save" type="submit" disabled={busy}
                  >{accountCopy.settings.save}</button
                >
              {/if}
            </div>
          </form>
        {/if}
      </div>
    {/if}
    {#if error !== null}<p class="error" role="alert">{accountCopy.errors[error]}</p>{/if}
    <NotifySettings {store} schools={user.schools.length} />
    <div class="group">
      <button
        class="row nav privacy"
        type="button"
        onclick={() => {
          showPrivacy(true);
        }}
      >
        <span class="label">{accountCopy.settings.privacyTitle}</span>
        <svg class="chevron" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M6 3.5l4.5 4.5L6 12.5" />
        </svg>
      </button>
    </div>
    {#if user.role !== 'admin'}
      <div class="group">
        <button
          class="row nav destructive"
          type="button"
          aria-expanded={deleteOpen}
          aria-controls="delete-account"
          onclick={() => {
            deleteOpen = !deleteOpen;
          }}
        >
          <span class="label">{accountCopy.settings.deleteTitle}</span>
        </button>
        {#if deleteOpen}
          <form id="delete-account" onsubmit={deleteAccount}>
            <label class="row field">
              <span class="label dim">{accountCopy.sheet.password}</span>
              <input
                bind:value={deletePassword}
                type="password"
                autocomplete="current-password"
                maxlength="128"
                required
              />
            </label>
            <button class="row nav destructive confirm" type="submit" disabled={busy}>
              {accountCopy.settings.deleteButton}
            </button>
          </form>
        {/if}
      </div>
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
    /* Rows that undo something: Turn off everywhere (NotifySettings.svelte), Delete account. */
    --destructive: #ff6961;

    position: fixed;
    top: calc(var(--inset-top) + var(--edge) + var(--bar-height) + 8px);
    right: calc(var(--inset-right) + var(--edge));
    z-index: 21;
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: 400px;
    /* --keyboard-lift and --visible-height come from keyboard.ts while a keyboard is up. */
    max-height: min(
      calc(100dvh - var(--inset-top) - var(--bar-height) - 2 * var(--edge) - 16px),
      calc(
        var(--visible-height, 100dvh) - var(--inset-top) - var(--bar-height) - 2 * var(--edge) -
          16px
      )
    );
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

  button.primary {
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

  button.primary:disabled {
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

  /* Settings: grouped rows, a label on the left and its value or control on the right.
     NotifySettings.svelte uses the same group and row. */
  .sheet :global(.group) {
    display: flex;
    flex: none;
    flex-direction: column;
    gap: 0;
    margin: 0;
    padding: 0;
    overflow: hidden;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 14px;
  }

  .sheet :global(.group > * + *:not(.sub)),
  .sheet :global(.group form:not(.row) > * + *) {
    border-top: 1px solid var(--border-1);
  }

  .sheet :global(.row) {
    display: flex;
    flex-direction: row;
    gap: 12px;
    align-items: center;
    min-height: 48px;
    margin: 0;
    padding: 0 16px;
    font-size: 15px;
    line-height: 20px;
    color: var(--text-1);
  }

  .sheet :global(.row .label) {
    flex: 1;
    min-width: 0;
  }

  .sheet :global(.row .value) {
    flex: none;
    max-width: 60%;
    overflow: hidden;
    color: var(--text-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sheet :global(label.row) {
    cursor: pointer;
  }

  /* A form inside a group is rows like the rest: no gap between them. */
  .group form {
    gap: 0;
  }

  /* A field in a row: its label on the left, what it holds on the right. */
  .field {
    display: flex;
    flex: 1;
    flex-direction: row;
    gap: 12px;
    align-items: center;
    min-width: 0;
    font-size: 15px;
    color: var(--text-1);
  }

  .field .label {
    flex: none;
  }

  .field input {
    flex: 1;
    width: 0;
    min-width: 0;
    height: 46px;
    padding: 0;
    font-size: 15px;
    color: var(--text-2);
    text-align: right;
    background: none;
    border: 0;
    border-radius: 0;
  }

  .field input::placeholder {
    color: var(--text-3);
  }

  .field input:focus,
  .field input:focus-visible {
    color: var(--text-1);
    outline: none;
  }

  .row:focus-within {
    background: color-mix(in srgb, var(--text-1) 4%, transparent);
  }

  /* Save shows on a row only once its field is edited: a plain word where the row ends. */
  .save {
    flex: none;
    padding: 6px 0 6px 4px;
    font: inherit;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-1);
    cursor: pointer;
    background: none;
    border: 0;
  }

  .save:disabled {
    cursor: default;
    opacity: 0.6;
  }

  .done {
    flex: none;
    font-size: 15px;
    color: var(--text-3);
  }

  .dim {
    color: var(--text-2);
  }

  .nav {
    width: 100%;
    font: inherit;
    font-size: 15px;
    text-align: left;
    cursor: pointer;
    background: none;
    border: 0;
  }

  .nav:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text-1) 4%, transparent);
  }

  .nav:disabled {
    cursor: default;
    opacity: 0.6;
  }

  .chevron {
    flex: none;
    width: 14px;
    height: 14px;
    fill: none;
    stroke: var(--text-3);
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 140ms ease;
  }

  .nav.open .chevron {
    transform: rotate(90deg);
  }

  .row.destructive {
    color: var(--destructive);
  }

  .confirm {
    font-weight: 600;
  }

  .prose {
    margin: 0;
    font-size: 15px;
    line-height: 23px;
    color: var(--text-1);
  }

  .title {
    display: flex;
    gap: 4px;
    align-items: center;
    min-width: 0;
  }

  .back {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    margin-left: -8px;
    padding: 0;
    color: var(--text-2);
    cursor: pointer;
    background: none;
    border: 0;
    border-radius: 50%;
  }

  .back:hover,
  .back:focus-visible {
    color: var(--text-1);
    background: var(--surface-2);
    outline: none;
  }

  .back svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
    stroke-linecap: round;
    stroke-linejoin: round;
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
      bottom: var(--keyboard-lift, 0px);
      left: 0;
      width: auto;
      max-height: min(
        calc(100dvh - var(--inset-top) - 24px),
        calc(var(--visible-height, 100dvh) - 8px)
      );
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
