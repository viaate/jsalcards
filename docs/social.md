# Posts on X (@SnowlightMap): runbook

`.github/workflows/social-post.yml` posts on the X account @SnowlightMap by itself: queued
posts written ahead, and once a day a short post Claude Haiku writes from the facts file.
Every post carries a branded card made fresh from the real map at post time and passes the
same checks first. Code: `pipeline/snowlight/social/`.

**To stop it:** Actions > **social-post** > **...** > **Disable workflow** (it works from
GitHub mobile). Deleting the workflow file or removing the X secrets from the `x-posting`
environment stops it too. Nothing else posts on the account.

X asks that an account posting by itself carries its **Automated** label: on X, the
account's Settings > Your account > Account information > Automation, with the owner's
own account as the managing one.

## What posts, and when

- **Queued posts** (`social/queue/<NNNN>.json`): a push to the default branch
  that changes `social/queue/` posts the oldest one not posted yet. The daily run posts one
  too if one is waiting. A queued post is posted at most once, ever.
- **The daily post**: the scheduled run at 16:37 UTC (late morning in the US). With nothing
  queued, `ANTHROPIC_API_KEY` set and nothing posted in the last 20 hours, Haiku
  (`claude-haiku-5-5`) writes one post, in turn a dev log and a "join the waitlist" post,
  from `social/facts.md`, the subjects of the commits since the last post, and the run's
  fresh card with its description (the only facts about the picture it may use). Without
  the key the run says "no Anthropic key" and posts only queued posts.

## Caps (in code, tested)

- At most **1 post a run**, **2 posts a UTC day** of every kind (the D1 claim that starts a
  post holds the cap, so two runs cannot both pass it), and **1 Haiku post a UTC day** (its
  record is named by the day).
- At most **4 Haiku calls a run** (write, check, and one more try of each), each capped at
  **1,024 output tokens**, effort `low`, and no SDK retries. A day's Haiku cost is a fraction
  of a cent.
- X bills each post on the owner's prepaid credits. Keep the balance small and auto-recharge
  off: the most anything can ever spend is that balance.

## Checks every post passes

`pipeline/snowlight/social/rules.py`, before anything is sent:

- at most 270 characters as X counts them; no URL, domain or @mention (the link is in the
  bio); at most one hashtag and one emoji; no `!!` and no em dash;
- no banned words: hype ("most accurate", "revolutionary", "AI-powered", "guaranteed",
  "never wrong", "better than"), other calculators or sites by name, "SDC", "formula",
  "reconstruction", station call letters;
- every number is in `social/facts.md` or the image's description;
- a sentence that names a TESTING or COMING fact says it is testing or coming, and never
  calls it live; an image not from today is never called "right now" or "tonight";
- a waitlist post says "link in my bio".

A Haiku post also goes past a second Haiku call that checks it against the facts and
answers `{ok, problems}`. Either check failing gives one more try with the problems shown;
a second failure means no post that day (the run log says why). A queued post that fails the
checks is never sent and turns the run red.

## The facts file

`social/facts.md` is the only source of what a post may say. One fact a line, tagged
**LIVE** (true and running now), **TESTING** (built, but in practice mode or behind the
lock) or **COMING** (not on yet), with the words that name it. Keep it current: when
something ships, move its fact to LIVE in the same change. Nothing private goes in it. A
line printed on a card (the A card's "Every school closing in the US on one map, coming
this winter", the B card's "Building Snowlight") must be a LIVE or COMING fact's words; a
test holds them to it.

## The picture: a fresh card at post time

The job's **Render** step (no secret; `snowlight social render`, `render.py`) makes every
post's picture fresh:

1. Headless Chromium (installed in the job) reads the site's lock check from its own page and
   unlocks it in that browser only (never printed). Signed out, it opens the map at a view
   where the site reads the school directory and `live/closings.json`, and keeps their bytes;
   it reads `predictions/latest.json` from the same live root.
2. `picture.py` picks the view from those files: the busiest picture-sized area of lit
   schools when closings light any today; else the district with the highest chance of no
   school (at least 10%), framed by its schools on the left; else the national map at night.
   It writes the description (time with its zone, place by state, counts, chance) and the
   same facts as fields. Nothing is said about closings when the closings file was a 404
   (practice mode). No district is named.
3. It opens that view served exactly those files, hides every piece of the site's interface
   with a style in that page only, waits until the map is at rest (twice), checks that the
   map lit as many schools as the description counts at the zoom asked, and takes a
   1600 x 900 picture of the map alone.
4. `cards.py` lays the Snowlight card over it for each kind of post (`dev-log`, `waitlist`)
   from three templates in `pipeline/snowlight/social/cards/` (the site's Geist fonts, OFL):
   **C stamp** for closings and chance pictures, **A broadcast** for calm ones, **B framed**
   (the map whole in a frame, the words beside it) only where neither fits. A style fits
   when its words, stamp and logo darken at most 3% of the map's lit-school pixels
   (measured on the picture); the order is C, A, B for closings and districts and A, C, B
   for calm maps. The log says which style and why. Every word, number, place and time on
   the card comes from the picture's facts, never from Haiku: counts in the picture say "in
   this view", the country's total says "across the US", the chance is a number on the card
   (the map draws none). The alt text is built from the same facts and set on the image.

A try that fails gets one more. When the map fails twice, or a card fails twice, that post
goes with the library's newest card for its style: `social/images/<id>.png` and `.json`,
real cards made the same way with `snowlight social render --fallback`, dated on their face
("From Oct 26, 2026", never a clock, "now" or "live"), each with what it shows, its day and
alt text. A post never calls an older card current.

## The X token

The app uses OAuth 2.0 user tokens: an access token lasts about 2 hours and the refresh
token changes every time it is used. Each run that posts:

1. takes a lease on the token row in the D1 database `snowlight-live-state` (one run at a
   time can spend the token; the job's concurrency group also keeps one run at a time);
2. refreshes with the stored refresh token, or with the `X_REFRESH_TOKEN` secret when no
   token is stored yet or the secret is newer than the stored chain (the row keeps a keyed
   fingerprint of the secret the chain started from, so a newly pasted secret is noticed);
3. stores the new refresh token right away, sealed with AES-256-GCM under a key derived
   (HKDF-SHA256) from `X_CLIENT_SECRET`, with `UPDATE ... WHERE version = <read> AND lease =
<this run>`: the version goes up by one, and a run that lost the row stores nothing;
4. uploads the card (`POST /2/media/upload`, scope `media.write`), sets its alt text
   (`POST /2/media/metadata`; the post goes without it if X refuses) and posts
   (`POST /2/tweets`), recording the post id in D1.

If X refuses the refresh token, the run opens one issue, **X posting stopped: refresh
token**, with the steps below, and stops; it never retries in a loop. The issue closes
itself when a refresh works again.

### When the issue opens (the owner)

1. X developer console > the app of @SnowlightMap > **Keys and tokens** > OAuth 2.0:
   generate a new access token and refresh token (scopes: tweet.read, tweet.write,
   users.read, offline.access, media.write).
2. GitHub > Settings > Environments > **x-posting** > `X_REFRESH_TOKEN` > edit, paste the
   new refresh token, save.
3. Done: the next run (daily at 16:37 UTC, or a push to `social/queue/`) starts from it.

## Secrets (the owner adds them; never paste them anywhere else)

| Secret                                              | Where                      | What for                                                        |
| --------------------------------------------------- | -------------------------- | --------------------------------------------------------------- |
| `X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_REFRESH_TOKEN` | environment `x-posting`    | the X app and the first refresh token                           |
| `ANTHROPIC_API_KEY`                                 | environment `x-posting`    | Haiku's daily post (a dedicated key with a monthly spend limit) |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`     | repository (already there) | the D1 store                                                    |

The `x-posting` environment is limited to the default branch. The workflow has no trigger a
fork or pull request can fire (no `pull_request`, `pull_request_target` or
`workflow_dispatch`), checks the branch again in its first step, gives the secrets to the
post step alone, masks every token it derives, writes nothing to files, artifacts, caches
or the step summary, and pins its two actions by full commit SHA. Its `log-check` job reads
the post job's own log and fails on any secret-shaped value. If a key ever leaks,
regenerate it in the X or Anthropic console and paste the new one.

## What the log shows

One line per step: what was picked and why, the token version stored, the post id and its
URL, the posted text. Never a token, a key, or an answer's body.
