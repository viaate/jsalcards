<script lang="ts">
  import { onMount } from 'svelte';

  import { accountFormat, adminCopy } from '../copy-account';
  import UserTag from '../ui/account/UserTag.svelte';
  import { MAX_TERMS, type AdminCall, type ModerationTerm, type ScanMatch } from './call';

  interface Props {
    call: AdminCall;
  }

  let { call }: Props = $props();

  type Kind = ModerationTerm['kind'];
  const KINDS: readonly Kind[] = ['substring', 'token', 'raw', 'allow'];

  let terms = $state<ModerationTerm[] | null>(null);
  let term = $state('');
  let kind = $state<Kind>('substring');
  let busy = $state(false);
  let failed = $state(false);
  /** The kind chosen already holds as many words as the Worker keeps. */
  const full = $derived(
    terms !== null && terms.filter((item) => item.kind === kind).length >= MAX_TERMS,
  );
  /** The last scan: what it looked for (a term, or everything), how far it got and what it caught. */
  let scan = $state<{
    term: string | null;
    done: boolean;
    scanned: number;
    matches: ScanMatch[];
  } | null>(null);
  let renamed = $state<ReadonlySet<string>>(new Set());

  async function load(): Promise<void> {
    try {
      const body = await call<{ terms: ModerationTerm[] }>('GET', '/v1/admin/moderation');
      terms = body.terms;
    } catch {
      failed = true;
      terms = terms ?? [];
    }
  }

  /** Reads every username a page at a time (each page is one short request). */
  async function runScan(word: string | null, wordKind: Kind): Promise<void> {
    const found: ScanMatch[] = [];
    scan = { term: word, done: false, scanned: 0, matches: [] };
    let after = '';
    let scanned = 0;
    for (;;) {
      const params = new URLSearchParams(
        word === null ? { after } : { after, term: word, kind: wordKind },
      );
      const page = await call<{ matches: ScanMatch[]; scanned: number; next: string | null }>(
        'GET',
        `/v1/admin/moderation/scan?${params.toString()}`,
      );
      found.push(...page.matches);
      scanned += page.scanned;
      scan = { term: word, done: page.next === null, scanned, matches: [...found] };
      if (page.next === null) return;
      after = page.next;
    }
  }

  async function add(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy || full || term.trim() === '') return;
    busy = true;
    failed = false;
    try {
      const added = await call<{ term: string; kind: Kind }>('POST', '/v1/admin/moderation/terms', {
        term: term.trim(),
        kind,
      });
      term = '';
      await load();
      // A new blocked word lists every username it catches.
      if (added.kind !== 'allow') await runScan(added.term, added.kind);
    } catch {
      failed = true;
    } finally {
      busy = false;
    }
  }

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    failed = false;
    try {
      await action();
    } catch {
      failed = true;
    } finally {
      busy = false;
    }
  }

  function remove(item: ModerationTerm): void {
    void act(async () => {
      await call(
        'DELETE',
        `/v1/admin/moderation/terms/${encodeURIComponent(`${item.kind}:${item.term}`)}`,
      );
      await load();
    });
  }

  function rename(match: ScanMatch): void {
    void act(async () => {
      // A name a list word caught: that word already blocks it for everyone.
      await call('POST', `/v1/admin/users/${match.id}/rename`, { block: false });
      renamed = new Set([...renamed, match.id]);
    });
  }

  onMount(() => {
    void load();
  });
</script>

<section>
  <p class="muted">{adminCopy.moderation.intro}</p>
  <form class="add" onsubmit={add}>
    <input
      class="find"
      bind:value={term}
      maxlength="20"
      autocapitalize="none"
      spellcheck="false"
      aria-label={adminCopy.moderation.term}
      placeholder={adminCopy.moderation.term}
    />
    <select bind:value={kind} aria-label={adminCopy.moderation.kind}>
      {#each KINDS as option (option)}
        <option value={option}>{adminCopy.moderation[option]}</option>
      {/each}
    </select>
    <button class="button primary" type="submit" disabled={busy}>{adminCopy.moderation.add}</button>
    <button
      class="button"
      type="button"
      disabled={busy}
      onclick={() => void act(() => runScan(null, 'substring'))}
      >{adminCopy.moderation.scanAll}</button
    >
  </form>
  {#if full}<p class="error" role="alert">{adminCopy.moderation.full}</p>{/if}
  {#if failed}<p class="error" role="alert">{adminCopy.errors.failed}</p>{/if}

  {#if scan !== null}
    <h3>{scan.term === null ? adminCopy.moderation.caughtAll : adminCopy.moderation.caught}</h3>
    <p class="muted">
      {scan.done ? accountFormat.scanned(scan.scanned) : adminCopy.moderation.scanning}
    </p>
    {#if scan.done && scan.matches.length === 0}
      <p class="muted">{adminCopy.moderation.noneCaught}</p>
    {:else}
      <ul class="matches">
        {#each scan.matches as match (match.id)}
          <li>
            <UserTag username={match.username} joinNumber={match.join_number} />
            <span class="muted">{match.term}</span>
            {#if renamed.has(match.id)}
              <span class="muted">{adminCopy.moderation.renamed}</span>
            {:else}
              <button
                class="button"
                type="button"
                disabled={busy}
                onclick={() => {
                  rename(match);
                }}>{adminCopy.moderation.rename}</button
              >
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}

  <h3>{adminCopy.moderation.added}</h3>
  {#if terms === null}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if terms.length === 0}
    <p class="muted">{adminCopy.moderation.none}</p>
  {:else}
    <ul class="matches">
      {#each terms as item (`${item.kind}:${item.term}`)}
        <li>
          <span>{item.term}</span>
          <span class="muted">{adminCopy.moderation[item.kind]}</span>
          <button
            class="button"
            type="button"
            disabled={busy}
            onclick={() => {
              remove(item);
            }}>{adminCopy.moderation.remove}</button
          >
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  h3 {
    margin: 8px 0 0;
    font-size: 14px;
    font-weight: 600;
  }

  .add {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  .find {
    width: min(100%, 320px);
  }

  select {
    height: 36px;
    padding: 0 8px;
    font: inherit;
    font-size: 14px;
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 8px;
  }

  .matches {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .matches li {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }

  .muted {
    color: var(--text-2);
  }

  .error {
    color: var(--status-delayed);
  }
</style>
