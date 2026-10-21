# Accounts and the admin view

Snowlight has accounts: anyone 13 or older can sign up with a username, log in
with that username or their email, see their name at the top right, keep up to
5 saved schools, and change or delete their account in Settings. Each account
gets a join number in sign-up order, #0001 to #9999, shown in a small box after
its username. You (the owner) log in as the admin, **Olivia**, and get
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
2. In the **Username or email** box type `Olivia` (any capitals), and your admin password.
3. Press **Log in**. Your name shows at the top right.
4. Press your name > **Admin**. Or open the site with `?admin` at the end of
   the address, for example `https://snowlightmap.com/?admin`.

The admin view has five parts:

- **Overview**: how many accounts there are and how many are new, the latest
  chances file (when it was made, how old it is, how many districts are at 50%
  or more today and tomorrow, the 20 highest chances), how old the closings file
  is, how many manual statuses are on, the latest run of each workflow, and any
  open issues. Workflow runs and issues are read from GitHub's public API; if
  GitHub limits reads from your network, the page says so.
- **Statuses**: find a school or district (by name, or by typing its NCES id),
  see what the map shows for it now, and set **Closed**, **Delayed** (minutes),
  **Early dismissal** (time) or **Open**, for the whole district or that one
  school, and pick its days in that school's own time zone: **Today**,
  **Tomorrow** or **Today and tomorrow**, each with its dates (Today until 3 PM
  there, then Tomorrow). The dates you see are the dates saved: if the school's
  midnight passes while the form is open, the choices move on, and a day that
  is over asks you to pick again. If the school's time zone cannot be read (the
  chances file is missing or for another directory), the form says so and sets
  nothing. Saving again replaces the status, days and all, so a day you leave
  out comes off the map. Each status lists its days, each showing **Waiting to
  publish** until the closings file carries exactly that status at every school
  it covers, then **On the map**; a district status whose every school has a
  school status of its own that day shows **Each school has its own status**.
  **Clear** removes one. A note you add is seen only by admins. On the
  map, a status you set says "Confirmed by our team" in the school's panel.
- **Users**: find people by name, username or email; see their username and
  join number, when they joined and last logged in and how many schools they
  saved; rename them (see below); reset a password (the page makes a
  temporary password and shows it to you once, for you to pass on); disable,
  enable or delete an account.
- **Moderation**: the words no username may contain. Add your own (anywhere in
  a name, only as a whole word, or always allowed) and they apply at once.
  Adding a blocked word checks every existing username and lists each one it
  catches, with a button to rename it. **Check every username** does the same
  for all the lists together. Accounts you renamed are left out until they
  pick their new name.
- **Audit**: every admin action, newest first.

## Usernames and join numbers

- A username is 3 to 20 letters, numbers or underscores, not all numbers, with
  no underscore at either end or two in a row. Capitals do not count: `Snow_Fox`
  and `snow_fox` are the same name, and it is stored in small letters.
- Names that look like staff are reserved in any spelling: admin,
  administrator, mod, moderator, staff, support, help, official, team,
  snowlight, snowlightmap, system, root, null, undefined, everyone, here, your
  own name (Olivia), and `player_` followed by a number. The staff words are
  also refused with a common word typed on to them (`themod`, `modteam`,
  `staffbot`).
- The blocklist is built in (`api/src/usernames/blocklist.ts`) and checked by
  the accounts service on every sign up and rename; the sign up form checks it
  as you type too. It sees through numbers for letters (`5h1t`), repeated
  letters, underscores between letters, words spelled backwards and a word
  typed on to a common one (my, the, big, lord, boy, gang and about 70 more),
  and leaves innocent words alone (Scunthorpe, cocktail, grape, class, Sussex).
- **Renaming someone**: in **Users** or **Moderation**, press **Rename**. Type a
  new name, or leave it empty to give them `player_` and their join number (for
  example `player_0042`). The next time they open the site they must pick a new
  username before anything else, and the blocklist applies. The name you took
  away is held for good: nobody, them included, can pick the same letters
  again in any case, with underscores or digits added, dropped or moved, or
  with digits for letters (`Mean_Name`, `meanname7`, `7_mean_name_2010`,
  `m3anname`); the hold keeps only a scrambled form of those letters, not the
  name. **Also block this word for everyone** (on unless you turn it off) goes
  further: it adds the old name's letters to your blocked words (anywhere in
  a name when they are 4 letters or more, as a whole word when 3, not at all
  when fewer), so the name with any other word, letters or spelling trick
  around it (`the_meanname`, `meannamelord`) is refused too, and you can
  remove it in **Moderation**. The page says when it could not add the word
  (too short, or 50 words of that kind already). **Rename** in **Moderation**
  does not add a word, since a blocked word already caught that name. The
  admin log keeps the old and new names.
- **Join numbers**: you are always #0001. Accounts that existed before
  usernames got numbers in the order they signed up. Each new account gets the
  next one, up to #9999; accounts after that get no number and no box, and
  never get one later. The service keeps one counter that only goes up, taken
  in one step with the new account, so a number is never given out twice,
  even after its account is deleted, and never changes. You can see them but
  not edit them.
- **Sign-up limits**: 5 sign-ups an hour from one address, and 20 a day from
  one network (all the addresses that share the first three parts of an IPv4
  address, or the first four groups of an IPv6 one), so one person cannot use
  up the join numbers. The **Overview** lists any network with 5 or more
  sign-ups in a day this week. The service keeps those per-network counts (the
  network, never a full address) for 14 days.
- Accounts made before usernames are asked to pick one the next time they log
  in (by email), before anything else.

## Changing the admin password

1. On GitHub: **Settings** > **Secrets and variables** > **Actions** >
   **ADMIN_PASSWORD** > **Update secret**, and save the new password.
2. **Actions** > **API** > **Run workflow** > **Run workflow**.

When that run finishes, the new password works, the old one does not, and any
admin session made with the old one ends at once.

## What an account keeps

For each person: their name, email, username, join number, saved schools,
when they signed up and last logged in, and salted hashes of the two keys their
browser derived from their password (one for logging in by email, one by
username, each with its own salt; never the password). Sessions are
random tokens of which only a hash is kept; they last 30 days from the last
visit and end at log out, a password change, or when the account is disabled or
deleted.

Deleting an account (in Settings, or by the admin) removes its name, email,
username, saved schools, keys, sessions and login counts at once. The admin log
names accounts only by their id, with the username and join number they had
when you acted on them; it never holds their email or name, and entries made
before usernames that named an email now name the account's id, or "deleted
user". The deleted account's join number stays retired, and for 30 days nobody
can take its username or a look-alike of it, so nobody can pass for that person
at once; for that the service keeps only a scrambled form of the name, linked to
nothing, and drops it after the 30 days. Cloudflare's own
restore points of the database (Time Travel) hold earlier states for 7 days on
the free plan, then those are gone too.

Sign up and log in are rate limited: 10 logins per 15 minutes per address, 10
per account by email and another 10 by username (a right one is not counted),
and 5 sign ups per hour per address. A username is public, so anyone can use
up its 10 tries; logging in by email still works then. Each try is counted
before the password is checked, so tries sent all at once cannot get past the
limit. The live username check and the login salt lookup are limited per
address too (120 and 30 per 15 minutes). Accounts are for people 13 and older; the sign up
form asks.

The admin name is public, so anyone can use up its 10 tries. When that happens:

- A network you logged in to the admin from in the last 30 days (your home
  wifi, your phone's connection) still gets in with the right password,
  unless that network has itself used up 10 tries in the same 15 minutes.
- A new network is turned away until 15 minutes after the tries began.
- An admin session that is already open stays open.

## How it fits together (for whoever works on it next)

- `api/` is the Worker (`snowlight-api`) and its D1 migrations (`0003_usernames.sql`
  adds usernames, join numbers and the admin's moderation words; every
  migration only adds, so it is safe on the live database). Its tests run it
  in Miniflare (`cd api && npm ci && npm test`). The free plan gives a Worker
  10 ms of CPU per request, so the Worker does no slow hashing: the browser
  derives the key (`web/src/account/key.ts`), and `api/scripts/derive-key.mjs`
  does the same for the admin in the deploy runner. Both are checked against
  one test vector. An email key is salted with SHA-256 of "snowlight-v1|" and
  the email, as in v1, so the browser makes it itself. A username key has its
  own random salt, which the browser asks the Worker for (`POST /v1/login/salt`);
  a username nobody has gets a made-up salt that never changes (from a random
  secret the migration keeps in D1), and every email gets its v1 salt whether
  it has an account or not. So nobody can tell from outside which email belongs
  to which username, or whether an email or a username has an account.
- `api/src/usernames/` holds the username rules and the blocklist, shared by
  the Worker and the sign up form. The list starts from the "List of Dirty,
  Naughty, Obscene, and Otherwise Bad Words" (English, CC BY 4.0, attributed in
  the file) with additions and an allowlist. The lists compile when the Worker
  starts, so a check takes tens of microseconds; the admin keeps at most 50
  words of each kind, and a scan reads 20 usernames per request, so every
  request stays well under the 10 ms limit.
- `.github/workflows/api.yml` deploys it. `preview.yml` finds the API root (the
  `SNOWLIGHT_API_ROOT` repository variable overrides it) and builds the site
  with it; without one the site has no account controls.
- `GET /v1/overrides` is the public list of active manual statuses (no notes,
  no names). `live-ingest.yml` reads it and publishes them into
  `live/closings.json`, so the map shows them within about 10 minutes.
- Notifications come next: push subscriptions and notification settings will be
  new tables in a later migration, tied to `users.id`.
