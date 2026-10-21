<script lang="ts">
  import { onMount } from 'svelte';

  import { deriveWithSalt, loginSalt, randomSalt, temporaryPassword } from '../account/key';
  import UserTag from '../ui/account/UserTag.svelte';
  import { accountFormat, adminCopy } from '../copy-account';
  import { renameNoteFor, type AdminCall, type AdminUser, type RenameResult } from './call';

  interface Props {
    call: AdminCall;
  }

  let { call }: Props = $props();

  let query = $state('');
  let page = $state(1);
  let users = $state<AdminUser[] | null>(null);
  let total = $state(0);
  let pageSize = $state(50);
  let busy = $state(false);
  let failed = $state(false);
  /** The account whose delete waits for a second press. */
  let confirming = $state<string | null>(null);
  /** A temporary password just made, shown once, with whose it is. */
  let temporary = $state<{ id: string; password: string } | null>(null);
  /** The account being renamed, and the name typed for it (empty: a player number). */
  let renaming = $state<string | null>(null);
  let renameTo = $state('');
  /** "Also block this word for everyone": on unless the admin turns it off. */
  let renameBlock = $state(true);
  /** What the last rename did with the old name's word, for the note under the list. */
  let renameNote = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function load(): Promise<void> {
    try {
      const params = new URLSearchParams({ q: query.trim(), page: String(page) });
      const body = await call<{ users: AdminUser[]; total: number; page_size: number }>(
        'GET',
        `/v1/admin/users?${params.toString()}`,
      );
      users = body.users;
      total = body.total;
      pageSize = body.page_size;
    } catch {
      failed = true;
      users = users ?? [];
    }
  }

  function onInput(): void {
    clearTimeout(timer);
    timer = setTimeout(() => {
      page = 1;
      void load();
    }, 200);
  }

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    failed = false;
    try {
      await action();
      await load();
    } catch {
      failed = true;
    } finally {
      busy = false;
    }
  }

  /** The admin's browser makes the password and sends only its key; the password shows once here. */
  async function reset(user: AdminUser): Promise<void> {
    if (user.email === null) return;
    const password = temporaryPassword();
    // Both logins' keys: the email key salted with the email's v1 salt, the username key with a fresh one (account/key.ts).
    const emailSalt = await loginSalt(user.email);
    const nameSalt = randomSalt();
    const [key, nameKey] = await Promise.all([
      deriveWithSalt(emailSalt, password),
      deriveWithSalt(nameSalt, password),
    ]);
    await act(() =>
      call('POST', `/v1/admin/users/${user.id}/reset-password`, {
        key,
        email_salt: emailSalt,
        name_key: nameKey,
        name_salt: nameSalt,
      }),
    );
    if (!failed) temporary = { id: user.id, password };
  }

  /** Renames to the typed name, or to a player number when it is empty; the account picks anew. */
  async function rename(user: AdminUser): Promise<void> {
    const username = renameTo.trim();
    let result: RenameResult | null = null;
    await act(async () => {
      result = await call<RenameResult>(
        'POST',
        `/v1/admin/users/${user.id}/rename`,
        username === '' ? { block: renameBlock } : { username, block: renameBlock },
      );
    });
    if (!failed) {
      renaming = null;
      renameTo = '';
      renameNote = renameNoteFor(result);
    }
  }

  onMount(() => {
    void load();
    return () => {
      clearTimeout(timer);
    };
  });

  const pages = $derived(Math.max(1, Math.ceil(total / pageSize)));
</script>

<section>
  <input
    class="find"
    type="search"
    bind:value={query}
    oninput={onInput}
    aria-label={adminCopy.users.search}
    placeholder={adminCopy.users.search}
    autocomplete="off"
  />
  <p class="muted">{accountFormat.accounts(total)}</p>
  {#if failed}<p class="error" role="alert">{adminCopy.errors.failed}</p>{/if}
  {#if renameNote !== null}<p class="muted" role="status">{renameNote}</p>{/if}
  {#if users === null}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if users.length === 0}
    <p class="muted">{adminCopy.users.none}</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>{adminCopy.users.name}</th>
            <th>{adminCopy.users.username}</th>
            <th>{adminCopy.users.email}</th>
            <th>{adminCopy.users.created}</th>
            <th>{adminCopy.users.lastLogin}</th>
            <th>{adminCopy.users.schools}</th>
            <th>{adminCopy.users.state}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each users as user (user.id)}
            <tr>
              <td>{user.name}</td>
              <td>
                {#if user.username !== null}
                  <UserTag username={user.username} joinNumber={user.join_number} />
                {:else}
                  <span class="muted">{adminCopy.users.noUsername}</span>
                {/if}
                {#if user.rename_required}
                  <span class="muted pending">{adminCopy.users.renamePending}</span>
                {/if}
              </td>
              <td>{user.email ?? adminCopy.users.adminRow}</td>
              <td class="muted">{accountFormat.when(user.created_at)}</td>
              <td class="muted"
                >{user.last_login_at === null ? '' : accountFormat.when(user.last_login_at)}</td
              >
              <td>{accountFormat.number(user.schools)}</td>
              <td>{user.disabled ? adminCopy.users.disabled : adminCopy.users.active}</td>
              <td class="actions">
                {#if user.role !== 'admin'}
                  <button
                    class="button"
                    type="button"
                    disabled={busy}
                    onclick={() => {
                      renaming = renaming === user.id ? null : user.id;
                      renameTo = '';
                      renameBlock = true;
                      renameNote = null;
                    }}>{adminCopy.users.rename}</button
                  >
                  <button
                    class="button"
                    type="button"
                    disabled={busy}
                    onclick={() => void reset(user)}>{adminCopy.users.reset}</button
                  >
                  {#if user.disabled}
                    <button
                      class="button"
                      type="button"
                      disabled={busy}
                      onclick={() =>
                        void act(() => call('POST', `/v1/admin/users/${user.id}/enable`))}
                      >{adminCopy.users.enable}</button
                    >
                  {:else}
                    <button
                      class="button"
                      type="button"
                      disabled={busy}
                      onclick={() =>
                        void act(() => call('POST', `/v1/admin/users/${user.id}/disable`))}
                      >{adminCopy.users.disable}</button
                    >
                  {/if}
                  {#if confirming === user.id}
                    <button
                      class="button"
                      type="button"
                      disabled={busy}
                      aria-label={accountFormat.confirmDelete(user.email ?? user.name)}
                      onclick={() => {
                        confirming = null;
                        void act(() => call('DELETE', `/v1/admin/users/${user.id}`));
                      }}>{adminCopy.users.confirmDelete}</button
                    >
                  {:else}
                    <button
                      class="button"
                      type="button"
                      disabled={busy}
                      onclick={() => {
                        confirming = user.id;
                      }}>{adminCopy.users.delete}</button
                    >
                  {/if}
                {/if}
              </td>
            </tr>
            {#if renaming === user.id}
              <tr>
                <td colspan="8">
                  <form
                    class="rename"
                    onsubmit={(event) => {
                      event.preventDefault();
                      void rename(user);
                    }}
                  >
                    <input
                      class="find"
                      bind:value={renameTo}
                      maxlength="20"
                      autocapitalize="none"
                      spellcheck="false"
                      aria-label={adminCopy.users.renameTo}
                      placeholder={adminCopy.users.renameTo}
                    />
                    <label class="block">
                      <input type="checkbox" bind:checked={renameBlock} />
                      {adminCopy.users.renameBlock}
                    </label>
                    <button class="button" type="submit" disabled={busy}
                      >{adminCopy.users.renameSave}</button
                    >
                    <button
                      class="button"
                      type="button"
                      onclick={() => {
                        renaming = null;
                      }}>{adminCopy.users.renameCancel}</button
                    >
                  </form>
                </td>
              </tr>
            {/if}
            {#if temporary?.id === user.id}
              <tr>
                <td colspan="8">
                  <p class="muted">{adminCopy.users.temporary}</p>
                  <code class="temporary">{temporary.password}</code>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
    {#if pages > 1}
      <div class="pager">
        <button
          class="button"
          type="button"
          disabled={page <= 1}
          onclick={() => {
            page -= 1;
            void load();
          }}>{adminCopy.users.less}</button
        >
        <span class="muted">{accountFormat.page(page, pages)}</span>
        <button
          class="button"
          type="button"
          disabled={page >= pages}
          onclick={() => {
            page += 1;
            void load();
          }}>{adminCopy.users.more}</button
        >
      </div>
    {/if}
  {/if}
</section>

<style>
  .rename {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  .block {
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }

  .pending {
    display: block;
    font-size: 12px;
  }

  .find {
    width: min(100%, 420px);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .temporary {
    display: inline-block;
    margin-top: 4px;
    padding: 6px 10px;
    font-family: var(--font-mono);
    font-size: 15px;
    background: var(--surface-2);
    border-radius: 6px;
    user-select: all;
  }

  .pager {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-top: 12px;
  }
</style>
