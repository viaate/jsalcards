<script lang="ts">
  import { onMount } from 'svelte';

  import type { Services } from '../app/boot';
  import { accountFormat, adminCopy } from '../copy-account';
  import { fetchJson } from '../data/files';
  import { parsePredictions } from '../data/school-day';
  import { LIVE_CLOSINGS_PATH } from '../pwa/config';
  import { PUBLISHED_PATHS } from '../types/generated';
  import type { AdminCall, Summary } from './call';
  import {
    readIssues,
    readRuns,
    summarizePredictions,
    type Issue,
    type PredictionSummary,
    type RunSummary,
  } from './overview';

  interface Props {
    call: AdminCall;
    app: Services | null;
  }

  let { call, app }: Props = $props();

  let summary = $state<Summary | null | undefined>(undefined);
  let runs = $state<RunSummary[] | null>(null);
  let issues = $state<Issue[] | null | undefined>(undefined);
  let limited = $state(false);
  let predictions = $state<PredictionSummary | null | undefined>(undefined);
  let names = $state<((index: number) => string | null) | null>(null);
  let closingsAt = $state<string | null | undefined>(undefined);
  let now = $state(Date.now());

  async function loadPublished(services: Services): Promise<void> {
    const files = services.data.files;
    const read = async (path: string): Promise<unknown> => {
      if (!files.has(path)) return null;
      try {
        return await fetchJson(files, path, { cache: 'no-cache' });
      } catch {
        return null;
      }
    };
    const [rawPredictions, rawClosings] = await Promise.all([
      read(PUBLISHED_PATHS.predictions),
      read(LIVE_CLOSINGS_PATH),
    ]);
    const parsed = rawPredictions === null ? null : parsePredictions(rawPredictions);
    predictions = parsed === null ? null : summarizePredictions(parsed);
    const generated =
      typeof rawClosings === 'object' && rawClosings !== null && 'generated_at' in rawClosings
        ? rawClosings.generated_at
        : null;
    closingsAt = typeof generated === 'string' ? generated : null;
    if (parsed !== null) {
      const directory = await (await services.data.directories())?.get();
      if (directory !== undefined && directory !== null) {
        const list = directory.meta.districts.names;
        names = (index) => list[index] ?? null;
      }
    }
  }

  async function load(): Promise<void> {
    now = Date.now();
    const [counts, read, open] = await Promise.all([
      call<Summary>('GET', '/v1/admin/summary').catch(() => null),
      readRuns(),
      readIssues(),
    ]);
    summary = counts;
    runs = read.runs;
    issues = open.issues;
    limited = read.limited || open.limited;
  }

  onMount(() => {
    void load();
  });

  $effect(() => {
    if (app !== null) void loadPublished(app);
  });

  const ageOf = (iso: string): string => accountFormat.age(now - Date.parse(iso));
</script>

<section>
  <h3>{adminCopy.overview.accounts}</h3>
  {#if summary === undefined}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if summary === null}
    <p class="muted">{adminCopy.overview.unread}</p>
  {:else}
    <div class="tiles">
      <div class="tile">
        <span class="value">{accountFormat.number(summary.accounts.total)}</span><span class="label"
          >{adminCopy.overview.total}</span
        >
      </div>
      <div class="tile">
        <span class="value">{accountFormat.number(summary.accounts.new_day)}</span><span
          class="label">{adminCopy.overview.newDay}</span
        >
      </div>
      <div class="tile">
        <span class="value">{accountFormat.number(summary.accounts.new_week)}</span><span
          class="label">{adminCopy.overview.newWeek}</span
        >
      </div>
      <div class="tile">
        <span class="value">{accountFormat.number(summary.accounts.active_week)}</span><span
          class="label">{adminCopy.overview.activeWeek}</span
        >
      </div>
      <div class="tile">
        <span class="value">{accountFormat.number(summary.accounts.disabled)}</span><span
          class="label">{adminCopy.overview.disabled}</span
        >
      </div>
      <div class="tile">
        <span class="value">{accountFormat.number(summary.overrides_active)}</span><span
          class="label">{adminCopy.overview.manual}</span
        >
      </div>
    </div>
  {/if}
</section>

<section>
  <h3>{adminCopy.overview.chances}</h3>
  {#if predictions === undefined}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if predictions === null}
    <p class="muted">{adminCopy.overview.unread}</p>
  {:else}
    <div class="tiles">
      <div class="tile">
        <span class="value">{accountFormat.when(predictions.generatedAt)}</span><span class="label"
          >{adminCopy.overview.made}</span
        >
      </div>
      <div class="tile">
        <span class="value">{ageOf(predictions.generatedAt)}</span><span class="label"
          >{adminCopy.overview.age}</span
        >
      </div>
      <div class="tile">
        <span class="value">{accountFormat.number(predictions.today)}</span><span class="label"
          >{adminCopy.overview.today}</span
        >
      </div>
      {#if predictions.tomorrow !== null}
        <div class="tile">
          <span class="value">{accountFormat.number(predictions.tomorrow)}</span><span class="label"
            >{adminCopy.overview.tomorrow}</span
          >
        </div>
      {/if}
    </div>
    {#if predictions.top.length > 0}
      <h3 class="sub">{adminCopy.overview.top}</h3>
      <ol class="top">
        {#each predictions.top as row (row.district)}
          <li>
            <span
              >{names?.(row.district) ??
                accountFormat.target('district', String(row.district))}</span
            >
            <span class="muted">{accountFormat.percent(row.chance)}</span>
          </li>
        {/each}
      </ol>
    {/if}
  {/if}
</section>

<section>
  <h3>{adminCopy.overview.closings}</h3>
  {#if closingsAt === undefined}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if closingsAt === null}
    <p class="muted">{adminCopy.overview.unread}</p>
  {:else}
    <div class="tiles">
      <div class="tile">
        <span class="value">{accountFormat.when(closingsAt)}</span><span class="label"
          >{adminCopy.overview.made}</span
        >
      </div>
      <div class="tile">
        <span class="value">{ageOf(closingsAt)}</span><span class="label"
          >{adminCopy.overview.age}</span
        >
      </div>
    </div>
  {/if}
</section>

<section>
  <h3>{adminCopy.overview.runs}</h3>
  {#if limited}<p class="error">{adminCopy.overview.limited}</p>{/if}
  {#if runs === null}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else}
    <div class="scroll">
      <table>
        <tbody>
          {#each runs as run (run.workflow)}
            <tr>
              <th scope="row">{adminCopy.workflows[run.workflow]}</th>
              <td>
                {#if run.state === null}
                  <span class="muted">{adminCopy.overview.unread}</span>
                {:else if run.url !== null}
                  <a href={run.url} target="_blank" rel="noopener noreferrer"
                    >{adminCopy.runs[run.state]}</a
                  >
                {:else}
                  {adminCopy.runs[run.state]}
                {/if}
              </td>
              <td class="muted">{run.at === null ? '' : accountFormat.when(run.at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<section>
  <h3>{adminCopy.overview.issues}</h3>
  {#if issues === undefined}
    <p class="muted">{adminCopy.overview.loading}</p>
  {:else if issues === null}
    <p class="muted">{adminCopy.overview.unread}</p>
  {:else if issues.length === 0}
    <p class="muted">{adminCopy.overview.none}</p>
  {:else}
    <ul class="issues">
      {#each issues as issue (issue.url)}
        <li><a href={issue.url} target="_blank" rel="noopener noreferrer">{issue.title}</a></li>
      {/each}
    </ul>
  {/if}
  <button class="button" type="button" onclick={() => void load()}
    >{adminCopy.overview.refresh}</button
  >
</section>

<style>
  .sub {
    margin-top: 16px;
  }

  .top {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 4px 16px;
    margin: 0;
    padding: 0 0 0 20px;
    font-size: 13px;
  }

  .top li span:first-child {
    margin-right: 8px;
  }

  .issues {
    margin: 0 0 12px;
    padding-left: 20px;
    font-size: 13px;
    line-height: 22px;
  }
</style>
