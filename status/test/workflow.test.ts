import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { root } from './harness.ts';

const workflows = join(root, '..', '.github', 'workflows');
const read = (name: string): string => readFileSync(join(workflows, name), 'utf8');
const status = read('status.yml');

/** The entries of the list under `key:` that comes first after `from` in a workflow's text. */
function list(text: string, from: string, key: string): string[] {
  const start = text.indexOf(from);
  assert.notEqual(start, -1, from);
  const lines = text.slice(start).split('\n');
  const at = lines.findIndex((line) => line.trim() === `${key}:`);
  assert.notEqual(at, -1, key);
  const found: string[] = [];
  for (const line of lines.slice(at + 1)) {
    const trimmed = line.trim();
    if (trimmed.startsWith('#') || trimmed === '') continue;
    if (!trimmed.startsWith('- ')) break;
    found.push(trimmed.slice(2));
  }
  return found;
}

test('a change to the status page starts Status, not CI or Preview', () => {
  const ci = read('ci.yml');
  assert.deepEqual(list(ci, '\n  push:', 'paths-ignore'), [
    'pipeline/config/archive-requests.json',
    'ios/**',
    'status/**',
  ]);
  assert.deepEqual(list(ci, '\n  pull_request:', 'paths-ignore'), ['ios/**', 'status/**']);
  // CI still starts on status.yml itself: tests in its jobs read every workflow file.
  assert.equal(ci.includes('.github/workflows/status.yml'), false);
  assert.deepEqual(list(read('preview.yml'), '\n  push:', 'paths-ignore'), [
    'pipeline/config/archive-requests.json',
    'docs/**',
    'ios/**',
    '.github/workflows/ios-*.yml',
    'status/**',
    '.github/workflows/status.yml',
  ]);
  assert.deepEqual(list(status, '\n  push:', 'paths'), [
    'status/**',
    '.github/workflows/status.yml',
  ]);
});

test('the triggers, the permissions and the one-at-a-time rule', () => {
  assert.match(status, /^name: Status$/m);
  assert.match(
    status,
    /\non:\n  push:\n    paths:\n      - status\/\*\*\n      - \.github\/workflows\/status\.yml\n  workflow_dispatch:\n/,
  );
  assert.equal(/schedule:|pull_request|workflow_run/.test(status), false);
  assert.match(status, /\npermissions:\n  contents: read\n/);
  assert.equal((status.match(/permissions:/g) ?? []).length, 1);
  // A group of the branch's own: a push on another branch cannot displace a waiting deploy.
  assert.match(
    status,
    /\nconcurrency:\n  group: status-\$\{\{ github\.ref \}\}\n  cancel-in-progress: false\n/,
  );
  assert.equal(status.match(/^\s*group:/gm)?.length, 1);
  assert.equal((status.match(/WRANGLER_SEND_METRICS: "false"/g) ?? []).length, 2);
  // Actions are pinned as ci.yml pins them.
  const ci = read('ci.yml');
  for (const uses of new Set(status.match(/uses: \S+/g)))
    assert.equal(ci.includes(uses), true, uses);
  assert.match(
    status,
    /\n  deploy:\n    name: deploy\n    needs: test\n    if: github\.ref_name == github\.event\.repository\.default_branch\n/,
  );
});

test('the test job runs the four checks in the status folder', () => {
  const job = status.slice(status.indexOf('\n  test:'), status.indexOf('\n  deploy:'));
  assert.match(job, /working-directory: status\n/);
  assert.deepEqual(job.match(/- run: .*/g), [
    '- run: npm ci --prefer-offline --no-audit --no-fund',
    '- run: npm run check',
    '- run: npm test',
    '- run: npm run build',
  ]);
  assert.equal(job.includes('secrets.'), false);
});

const deploy = status.slice(status.indexOf('\n  deploy:'));

test('the deploy goes in order: the store notice comes before the Pages check', () => {
  const marks = [
    'The status page is not set up yet',
    'npm ci --prefer-offline --no-audit --no-fund',
    'npm run build',
    'npx wrangler d1 list --json',
    'npx wrangler d1 create snowlight-status',
    'sed -i "s/^database_id = .*/database_id = \\"${id}\\"/" prober/wrangler.toml page/wrangler.toml',
    'npx wrangler d1 migrations apply snowlight-status --remote',
    'npx wrangler deploy --var "ACCOUNTS_HEALTH_URL:${root%/}/v1/health" --var "LIVE_ROOT:${LIVE_ROOT}"',
    'npx wrangler d1 execute snowlight-status --remote --json',
    '::notice::${kept}; last at',
    '/pages/projects/snowlight-status" || true)"',
    'npx wrangler pages project create snowlight-status --production-branch main',
    'npx wrangler pages deploy dist --project-name snowlight-status --branch main',
    '--data \'{"name":"status.snowlightmap.com"}\'',
    '-X PATCH',
    'https://${sub}/api/status',
    '::notice::https://status.snowlightmap.com is live.',
  ];
  let at = -1;
  for (const mark of marks) {
    const next = deploy.indexOf(mark, at + 1);
    assert.equal(next > at, true, `out of order or missing: ${mark}`);
    at = next;
  }
  // Every step after the first waits for the secrets.
  const steps = deploy
    .slice(deploy.indexOf('    steps:'))
    .split(/\n      - /)
    .slice(1);
  assert.equal(steps.length, 13);
  assert.match(steps[0]!, /^id: secrets\n/);
  for (const step of steps.slice(1))
    assert.match(
      step,
      /^(id: db\n {8})?if: (always\(\) && )?steps\.secrets\.outputs\.enabled == 'true'\n/,
    );
  // Only the store notice runs after a failed step, so every run says what is kept; without
  // the database's id it says it could not read the store.
  const always = steps.filter((step) => step.includes('always()'));
  assert.equal(always.length, 1);
  assert.match(always[0]!, /name: Say what the checker has kept\n/);
  assert.match(always[0]!, /DB_ID: \$\{\{ steps\.db\.outputs\.id \}\}/);
  assert.match(
    always[0]!,
    /if \[ -z "\$\{DB_ID\}" \]; then\n\s+echo "::warning::The status checker store could not be read/,
  );
  assert.match(deploy, /id: db\n\s+if: [^\n]+\n\s+name: Find or make the database\n/);
  assert.match(deploy, /echo "id=\$\{id\}" >> "\$GITHUB_OUTPUT"/);
  assert.match(
    deploy,
    /--commit-hash "\$GITHUB_SHA" --commit-message "status \$\{GITHUB_SHA::7\}" --commit-dirty=true/,
  );
  assert.match(
    deploy,
    /LIVE_ROOT: \$\{\{ vars\.SNOWLIGHT_LIVE_ROOT \|\| 'https:\/\/viaate\.github\.io\/snowlight-live\/v1\/' \}\}/,
  );
  assert.match(deploy, /API_ROOT_OVERRIDE: \$\{\{ vars\.SNOWLIGHT_API_ROOT \}\}/);
});

test('the messages, word for word', () => {
  for (const message of [
    '::notice::The status page is not set up yet: add the CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID repository secrets (docs/accounts.md). Skipping the deploy.',
    '::error::Could not find or create the D1 database snowlight-status.',
    // Step 4, the store notice.
    'const kept = `status checker: ${row.n3} of the last 36 checks kept (3 hours), ${row.n24} of the last 288 (24 hours)`;',
    'console.log(`::notice::${kept}; none yet.`);',
    'console.log(`::notice::${kept}; last at ${at} UTC: website ${word(row.site)} ${code(row.site_code)}, closings ${word(row.closings)} ${code(row.closings_code)}, chances ${word(row.chances)} ${code(row.chances_code)}, accounts ${word(row.accounts)} ${code(row.accounts_code)}; largest closings file ${bytes} bytes.`);',
    '::warning::The status checker store could not be read, so this run cannot say what it has kept. The deploy goes on.',
    // Step 5, the Pages check.
    '::error::The Cloudflare token cannot manage Pages (HTTP ${code}). Add the permission Account / Cloudflare Pages / Edit to it, then run this workflow again (docs/status.md, step 1). The checker is deployed and is already keeping history.',
    "::error::Cloudflare's API answered HTTP ${code} for the Pages project. Run this workflow again.",
    // Step 7, the name.
    '::warning::Could not attach status.snowlightmap.com to the Pages project (HTTP ${code}). Attach it by hand (docs/status.md, step 3).',
    '::warning::Cloudflare did not take the request to look at status.snowlightmap.com again (HTTP ${code}). Run this workflow again.',
    // Step 8, the page check and the DNS notice.
    '::error::The status page did not answer at https://${sub}/api/status. Run this workflow again.',
    '::notice::https://status.snowlightmap.com is live.',
    '::notice::The status page is live at https://${sub}. To put it on status.snowlightmap.com, add this DNS record at GoDaddy: type CNAME, name status, value ${sub} (docs/status.md, step 2).',
  ]) {
    assert.equal(status.includes(message), true, message);
  }
  assert.match(deploy, /401 \| 403\)\n\s+echo "::error::The Cloudflare token cannot manage Pages/);
  // A 404 for a token without Pages: making the project fails, and the run names the permission.
  assert.match(
    deploy,
    /if ! npx wrangler pages project create snowlight-status --production-branch main; then\n\s+echo "::error::The Cloudflare token cannot manage Pages \(HTTP \$\{code\}\)\. Add the permission Account \/ Cloudflare Pages \/ Edit to it, then run this workflow again \(docs\/status\.md, step 1\)\. The checker is deployed and is already keeping history\."\n\s+exit 1\n/,
  );
  assert.match(deploy, /for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do\n[^]*?sleep 15\n/);
  // The store notice counts 3 hours and 24 hours, and reads the newest sample and the largest file.
  assert.match(deploy, /WHERE t > unixepoch\(\) - 10800\) AS n3/);
  assert.match(deploy, /WHERE t > unixepoch\(\) - 86400\) AS n24/);
  assert.match(
    deploy,
    /SELECT MAX\(closings_bytes\) FROM samples WHERE t > unixepoch\(\) - 86400\) AS bytes/,
  );
});

test('the token is only ever sent in an Authorization header', () => {
  const header = '-H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}"';
  let sent = 0;
  for (const line of status.split('\n')) {
    if (!line.includes('CLOUDFLARE_API_TOKEN')) continue;
    const trimmed = line.trim();
    if (trimmed.startsWith('#')) continue;
    if (/^[A-Z_]+: \$\{\{ secrets\.CLOUDFLARE_API_TOKEN( != '')? \}\}$/.test(trimmed)) continue;
    if (trimmed.startsWith('echo "::notice::The status page is not set up yet')) continue;
    assert.equal(line.split('CLOUDFLARE_API_TOKEN').length, 2, line);
    assert.equal(line.includes(header), true, line);
    sent += 1;
  }
  assert.equal(sent, 7);
  // Each request to Cloudflare's API carries it, quietly, and nothing echoes a command.
  const curls = status.split('\n').filter((line) => /\bcurl\b/.test(line));
  assert.equal(curls.length, 8);
  for (const line of curls) assert.match(line, /curl -sS /, line);
  assert.equal((status.match(/api\.cloudflare\.com/g) ?? []).length, 4);
  assert.equal(/set -x|set -o xtrace| -v\b| --verbose|--trace|--debug/.test(status), false);
  assert.equal(
    /(?<!steps\.)secrets\.(?!CLOUDFLARE_API_TOKEN|CLOUDFLARE_ACCOUNT_ID)/.test(status),
    false,
  );
  // An answer is parsed and only named fields leave it: no step prints a whole answer.
  assert.equal(/\bcat\b|\bjq\b|tee /.test(status), false);
});

test('both wrangler files hold the zero id until the deploy fills it in', () => {
  const zero = 'database_id = "00000000-0000-0000-0000-000000000000"';
  const prober = readFileSync(join(root, 'prober/wrangler.toml'), 'utf8');
  const page = readFileSync(join(root, 'page/wrangler.toml'), 'utf8');
  for (const text of [prober, page]) {
    assert.equal(
      text
        .split('\n')
        .filter((line) => line.startsWith('database_id'))
        .join(),
      zero,
    );
    assert.match(text, /binding = "DB"\ndatabase_name = "snowlight-status"\n/);
    assert.match(text, /compatibility_date = "2026-08-01"/);
  }
  assert.match(prober, /^name = "snowlight-status-prober"$/m);
  assert.match(prober, /^compatibility_flags = \["global_fetch_strictly_public"\]$/m);
  assert.match(prober, /^workers_dev = false\npreview_urls = false$/m);
  assert.match(prober, /\[triggers\]\ncrons = \["\*\/5 \* \* \* \*"\]/);
  assert.match(
    prober,
    /SITE_URL = "https:\/\/snowlightmap\.com\/"\nLIVE_ROOT = "https:\/\/viaate\.github\.io\/snowlight-live\/v1\/"\nACCOUNTS_HEALTH_URL = ""\n/,
  );
  assert.match(prober, /migrations_dir = "migrations"/);
  assert.match(page, /^name = "snowlight-status"\npages_build_output_dir = "dist"$/m);
});
