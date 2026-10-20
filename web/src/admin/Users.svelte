<script lang="ts">
  import { onMount } from 'svelte';

  import { deriveKey, temporaryPassword } from '../account/key';
  import { accountFormat, adminCopy } from '../copy-account';
  import type { AdminCall, AdminUser } from './call';

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
    const key = await deriveKey(user.email, password);
    await act(() => call('POST', `/v1/admin/users/${user.id}/reset-password`, { key }));
    if (!failed) temporary = { id: user.id, password };
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
            {#if temporary?.id === user.id}
              <tr>
                <td colspan="7">
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
