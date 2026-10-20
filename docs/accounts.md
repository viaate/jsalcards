# Accounts and the admin view

Snowlight has accounts: anyone 13 or older can sign up, log in, see their name
at the top right, keep up to 5 saved schools, and change or delete their
account in Settings. You (the owner) log in as the admin, **Olivia**, and get
an admin view with everything about the site in one place, including a way to
set a school's or a district's status by hand.

It costs nothing. It runs on Cloudflare's free Workers plan and the free D1
database on your existing Cloudflare account, and on GitHub Actions in this
public repository. No card, no paid feature, no domain or DNS change. If a free
daily limit were ever reached (100,000 requests a day for the Worker; 5 million
rows read and 100,000 rows written a day, and 5 GB stored, for the database),
the accounts would stop answering until the next day. Nothing is ever charged.

Until you add the three secrets below, nothing about accounts shows on the
site, and the deploy workflow prints one notice and stops without an error.

## What you do once: three secrets

All three go in the same place on GitHub: open the repository, then
**Settings** (top bar) > **Secrets and variables** (left side) > **Actions** >
**New repository secret**. Type the name exactly as written, paste the value,
and press **Add secret**.

### 1. CLOUDFLARE_ACCOUNT_ID

What it is: which Cloudflare account the accounts live in. It is not a password.

1. Go to <https://dash.cloudflare.com> and log in.
2. In the left sidebar, open **Workers & Pages** (under Compute).
3. On the right side of that page, find **Account ID** and press its copy button.
4. On GitHub, add a secret named `CLOUDFLARE_ACCOUNT_ID` with that value.

The first time you open Workers & Pages, Cloudflare can ask you to pick a
**workers.dev subdomain** (a free name such as `olivia-snow`). Pick any name and
confirm. The accounts API will live at
`https://snowlight-api.<that name>.workers.dev`.

### 2. CLOUDFLARE_API_TOKEN

What it is: a key that lets the deploy workflow put the accounts Worker and its
database on your account, and nothing else.

1. At <https://dash.cloudflare.com>, press your profile icon (top right) >
   **My Profile** > **API Tokens** (left side) > **Create Token**.
2. Next to **Edit Cloudflare Workers**, press **Use template**.
3. Under **Permissions**, press **+ Add more** and set the new row to
   **Account** / **D1** / **Edit**.
4. Delete the rows that start with **Zone** (press the X at the end of each),
   so the token cannot touch any website.
5. Under **Account Resources**, choose **Include** and your account.
6. If a **Zone Resources** section is still shown, leave it with no zones.
7. Press **Continue to summary**, then **Create Token**, and copy the token.
   Cloudflare shows it only once.
8. On GitHub, add a secret named `CLOUDFLARE_API_TOKEN` with that value.

### 3. ADMIN_PASSWORD

What it is: the password you log in with as Olivia.

1. On GitHub, add a secret named `ADMIN_PASSWORD` with your admin password.

Nobody else ever sees it, and it never leaves GitHub's runner: the deploy
workflow turns it into a scrambled key (600,000 rounds of PBKDF2, the same way
your browser does when you log in) and gives Cloudflare only that key. If this
secret is missing, nobody can log in as the admin.

## Turning it on

After the three secrets are in:

1. On GitHub, open **Actions** > **API** (left side) > **Run workflow** >
   **Run workflow**. In about two minutes it makes the database, deploys the
   Worker and sets the admin key. Its last step checks that the API answers.
2. Then open **Actions** > **Preview** > **Run workflow** > **Run workflow**, so
   the site is rebuilt knowing where the API is. (Any later push does this too.)

When the Preview run finishes, the site shows **Sign up or log in** at the top
right. If the API is ever down, the site simply hides the account controls.

## Logging in as the admin

1. Press **Sign up or log in** at the top right.
2. In the **Email** box type `Olivia` (any capitals), and your admin password.
3. Press **Log in**. Your name shows at the top right.
4. Press your name > **Admin**. Or open the site with `?admin` at the end of
   the address, for example `https://snowlightmap.com/?admin`.

The admin view has four parts:

- **Overview**: how many accounts there are and how many are new, the latest
  chances file (when it was made, how old it is, how many districts are at 50%
  or more today and tomorrow, the 20 highest chances), how old the closings file
  is, how many manual statuses are on, the latest run of each workflow, and any
  open issues. Workflow runs and issues are read from GitHub's public API; if
  GitHub limits reads from your network, the page says so.
- **Statuses**: find a school or district (by name, or by typing its NCES id),
  see what the map shows for it now, and set **Closed**, **Delayed** (minutes),
  **Early dismissal** (time) or **Open**, for the whole district or that one
  school. It ends at the end of that school's day today (or tomorrow, if you
  pick that). Each manual status shows **Waiting to publish** until the map
  shows it, then **On the map**. **Clear** removes one. A note you add is seen
  only by admins.
- **Users**: find people by name or email; see when they joined and last
  logged in and how many schools they saved; reset a password (the page makes
  a temporary password and shows it to you once, for you to pass on); disable,
  enable or delete an account.
- **Audit**: every admin action, newest first.

## Changing the admin password

1. On GitHub: **Settings** > **Secrets and variables** > **Actions** >
   **ADMIN_PASSWORD** > **Update secret**, and save the new password.
2. **Actions** > **API** > **Run workflow** > **Run workflow**.

When that run finishes, the new password works, the old one does not, and any
admin session made with the old one ends at once.

## What an account keeps

For each person: their name, email, saved schools, when they signed up and
last logged in, and a salted hash of the key their browser derived from their
password (never the password). Sessions are random tokens of which only a hash
is kept; they last 30 days from the last visit and end at log out, a password
change, or when the account is disabled or deleted. Deleting an account (in
Settings, or by the admin) removes all of it.

Sign up and log in are rate limited: 10 logins per 15 minutes per address and
per account (a right one is not counted), and 5 sign ups per hour per address.
Each try is counted before the password is checked, so tries sent all at once
cannot get past the limit. Accounts are for people 13 and older; the sign up
form asks.

The admin name is public, so anyone can use up its 10 tries. When that happens:

- A network you logged in to the admin from in the last 30 days (your home
  wifi, your phone's connection) still gets in with the right password,
  unless that network has itself used up 10 tries in the same 15 minutes.
- A new network is turned away until 15 minutes after the tries began.
- An admin session that is already open stays open.

## How it fits together (for whoever works on it next)

- `api/` is the Worker (`snowlight-api`) and its D1 migrations. Its tests run it
  in Miniflare (`cd api && npm ci && npm test`). The free plan gives a Worker
  10 ms of CPU per request, so the Worker does no slow hashing: the browser
  derives the key (`web/src/account/key.ts`), and `api/scripts/derive-key.mjs`
  does the same for the admin in the deploy runner. Both are checked against
  one test vector.
- `.github/workflows/api.yml` deploys it. `preview.yml` finds the API root (the
  `SNOWLIGHT_API_ROOT` repository variable overrides it) and builds the site
  with it; without one the site has no account controls.
- `GET /v1/overrides` is the public list of active manual statuses (no notes,
  no names). `live-ingest.yml` reads it and publishes them into
  `live/closings.json`, so the map shows them within about 10 minutes.
- Notifications come next: push subscriptions and notification settings will be
  new tables in a later migration, tied to `users.id`.
