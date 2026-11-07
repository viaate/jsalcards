<script lang="ts">
  import { onMount } from 'svelte';

  import type { Services } from '../app/boot';
  import { REASON_KEYS, STATUS_KEYS, copy } from '../copy';
  import { accountFormat, adminCopy } from '../copy-account';
  import type { Directory } from '../data/directory';
  import type { AdminCall } from './call';
  import ListLink from './ListLink.svelte';
  import { decodeDay, rowName, type SourcesDay, type StoredDay } from './sources';

  interface Props {
    call: AdminCall;
    /** The page's services, for the public directory the rows are named from (null: loading). */
    app: Services | null;
  }

  let { call, app }: Props = $props();

  let days = $state<SourcesDay[] | null>(null);
  let failed = $state(false);
  let directory = $state.raw<Directory | null>(null);

  $effect(() => {
    if (app === null || directory !== null) return;
    void app.data
      .directories()
      .then((source) => source?.get())
      .then((found) => {
        directory = found ?? null;
      })
      .catch(() => undefined);
  });

  function status(code: number | null): string {
    const key = code === null ? undefined : STATUS_KEYS[code];
    return key === undefined ? '' : copy.status[key];
  }

  function reason(code: number | null): string {
    const key = code === null ? undefined : REASON_KEYS[code];
    return key === undefined ? '' : copy.reason[key];
  }

  function time(iso: string | null): string {
    if (iso === null) return '';
    try {
      return accountFormat.when(iso);
    } catch {
      return '';
    }
  }

  onMount(() => {
    call<{ days: StoredDay[] }>('GET', '/v1/admin/sources').then(
      async (body) => {
        days = await Promise.all(body.days.map(decodeDay));
      },
      () => {
        failed = true;
        days = [];
      },
    );
  });
</script>

<section>
  {#if failed}<p class="error" role="alert">{adminCopy.errors.failed}</p>{/if}
  {#if days === null}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if days.length === 0}
    <p class="muted">{adminCopy.sources.none}</p>
  {:else}
    {#each days as day (day.day)}
      <h3>{accountFormat.listedDay(day.day)}</h3>
      <p class="muted">{adminCopy.sources.asOf} {time(day.publishedAt)}</p>
      {#if day.shadow}<p class="error">{adminCopy.sources.shadow}</p>{/if}
      {#if day.latestAt !== null}
        <p class="error">{adminCopy.sources.later} {time(day.latestAt)}</p>
        <p class="error">{adminCopy.sources.laterNote}</p>
      {/if}
      {#if day.rows === null}
        <p class="error" role="alert">
          {day.writing ? adminCopy.sources.writing : adminCopy.sources.unreadable}
        </p>
      {:else if day.rows.length === 0}
        <p class="muted">{adminCopy.sources.noneLit}</p>
      {:else}
        <div class="scroll">
          <table>
            <thead>
              <tr>
                <th>{adminCopy.sources.school}</th>
                <th>{adminCopy.sources.status}</th>
                <th>{adminCopy.sources.source}</th>
                <th>{adminCopy.sources.read}</th>
                <th>{adminCopy.sources.seen}</th>
                <th>{adminCopy.sources.present}</th>
                <th>{adminCopy.sources.posted}</th>
                <th>{adminCopy.sources.contributing}</th>
              </tr>
            </thead>
            <tbody>
              {#each day.rows as row, index (index)}
                {@const named = rowName(directory, row.nces)}
                <tr>
                  <td>
                    {#if named !== null}
                      <div>
                        {named.name}
                        <span class="muted"
                          >{accountFormat.stateOf(named.district?.id ?? named.id)}</span
                        >
                      </div>
                      {#if named.district !== null}<div class="muted">
                          {named.district.name}
                        </div>{/if}
                    {/if}
                    <div class="muted">{row.nces} {row.level ?? ''}</div>
                  </td>
                  <td>{status(row.status)} <span class="muted">{reason(row.reason)}</span></td>
                  <td><ListLink id={row.source} kind={row.type} links={day.links} /></td>
                  <td class="muted">{time(row.row_stamp)}</td>
                  <td class="muted">{time(row.hi)}</td>
                  <td>{row.present ? adminCopy.sources.yes : adminCopy.sources.no}</td>
                  <td><ListLink id={row.posted_by} kind={null} links={day.links} /></td>
                  <td>
                    {#each row.contributing as [id, kind] (id)}
                      <div><ListLink {id} {kind} links={day.links} /></div>
                    {/each}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {/each}
  {/if}
</section>
