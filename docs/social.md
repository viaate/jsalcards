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
- **The daily post**: the scheduled runs at 16:37 UTC (late morning in the US) and 20:41 UTC
  (a second slot, in case GitHub drops or delays the first). With nothing
  queued, `ANTHROPIC_API_KEY` set and nothing posted in the last 20 hours, Haiku
  (`claude-haiku-5-5`) writes one post, in turn a dev log and a "join the waitlist" post,
  from `social/facts.md`, the subjects of the commits since the last post, and the run's
  fresh card with its description (the only facts about the picture it may use). Without
  the key the run says "no Anthropic key" and posts only queued posts. The 20-hour rule and
  the day's Haiku record keep the second slot from posting twice.

## Caps (in code, tested)

- At most **1 post a run**, **2 posts a UTC day** of every kind (the D1 claim that starts a
  post holds the cap, so two runs cannot both pass it), and **1 Haiku post a UTC day** (its
  record is named by the day).
- At most **4 Haiku calls a run** (write, check, and one more try of each), each capped at
  **1,024 output tokens**, effort `low`, and no SDK retries. A day's Haiku cost is a fraction
  of a cent.
- X bills each post on the owner's prepaid credits. Keep the balance small and auto-recharge
  off: the most anything can ever spend is that balance.
- The spending limits are the owner's to set (nothing here can set them): in the X developer
  console, a spend cap (or a small prepaid balance with auto-recharge off) for the app; in
  the Anthropic console, a monthly spend limit on the dedicated key.

## Checks every post passes

`pipeline/snowlight/social/rules.py`, before anything is sent:

- at most 270 characters as X counts them; no URL, domain or @mention (the link is in the
  bio); at most one hashtag and one emoji; no `!!` and no em dash;
- no banned words: hype ("most accurate", "revolutionary", "AI-powered", "guaranteed",
  "never wrong", "better than"), other calculators or sites by name, "SDC", "formula",
  "reconstruction", station call letters;
- hype and comparisons as whole words: "best", "only", "unlike", "vs", "precise",
  "perfect", "spot on", "number one", "other apps";
- every number, in digits or in words ("fifty", "twenty-four", "first"), is in
  `social/facts.md` in the same form and used as the facts use it: a word next to it is next
  to it in the facts too ("24/7 in practice mode" passes, "24 schools" does not, nor "48
  schools" from "the lower 48 states"). A number from the picture's description is never
  written in a post: the card carries every count, time and chance, labeled. What this
  cannot see (a fact's number in a true-looking but misleading sentence that shares a word
  with the fact) is left to the second check;
- "tomorrow", "next week", a weekday or a month only as the facts or the picture's
  description use them; never a launch date;
- a sentence that names a TESTING or COMING fact (by its terms, such as "closings",
  "closed", "alerts", "text", "the map", "search") says it is testing or coming, and holds
  no live claim ("is live", "shows up", "ships", "works for everyone", "public now") and no
  end of testing ("no longer", "done testing", "practice is over"); a live claim that names
  no LIVE fact ("Snowlight is live") is refused too;
- a picture that is not current (a library card, or a fresh one of a stale closings file) is
  never called current: no "now", "today", "tonight", "currently", "as of", "just",
  "fresh", "latest" or clock time;
- a waitlist post says "link in my bio".

A Haiku post also goes past a second Haiku call that checks it against the facts and
answers `{ok, problems}`. Either check failing gives one more try with the problems shown;
a second failure means no post that day (the run log says why). A queued post that fails the
checks is never sent and turns the run red.

## The facts file

`social/facts.md` is the only source of what a post may say. One fact a line, tagged
**LIVE** (true and running now), **TESTING** (built, but in practice mode or behind the
lock) or **COMING** (not on yet), with the words that name it (`| terms: ...`) and the
phrases that hold one of those words but name another fact (`| except: ...`, such as
"closings reader", the LIVE reader, for the COMING closings on the map). Keep it current:
when something ships, move its fact to LIVE in the same change. Nothing private goes in
it. A line printed on a card (the A card's "Every school closing in the US on one map,
coming this winter", the B card's "Building Snowlight") must be a LIVE or COMING fact's
words; a test holds the templates to it, and a library card's line is kept in its JSON
(`tagline`): when that line leaves the facts file (the aim goes LIVE and is reworded), the
run stops red until the library is made again with `snowlight social render --fallback`.

## The picture: a fresh card at post time

The workflow's **render** job makes every post's picture fresh (`snowlight social render`,
`render.py`). It runs on its own machine with no secret, no environment and read-only
repository access, because its browser reads the live site and a third party's map tiles
with no sandbox; the secrets live only in the post job, which runs no browser:

1. Headless Chromium (installed in the job) reads the site's lock check from its own page and
   unlocks it in that browser only (never printed). Signed out, it opens the map at a view
   where the site reads the school directory and `live/closings.json`, and keeps their bytes;
   it reads `predictions/latest.json` from the same live root.
2. `picture.py` picks the view from those files: the busiest picture-sized area of lit
   schools when closings light any today; else the district with the highest chance of no
   school (at least 10%), framed by its schools on the left; else the dark national map (the
   words never say "night": the map is dark at any hour). It writes the description (time
   with its zone, place by state, counts, chance) and the same facts as fields. Nothing is
   said about closings when the closings file was a 404 (practice mode), and neither when it
   is older than 20 minutes: a stopped reader's empty file is no sign that nothing is
   closed, so that picture is not current and the post may not call it so. A chance is shown
   only from a predictions file at most 90 minutes old, for today until 3 PM Eastern, then
   for the next day. No district is named.
3. It opens that view served exactly those files, hides every piece of the site's interface
   with a style in that page only, waits until the map is at rest (twice), checks that the
   map lit as many schools as the description counts at the zoom asked, and takes a
   1600 x 900 picture of the map alone.
4. `cards.py` lays the Snowlight card over it for each kind of post (`dev-log`, `waitlist`)
   from three templates in `pipeline/snowlight/social/cards/` (the site's Geist fonts, OFL):
   **C stamp** for closings and chance pictures, **A broadcast** for calm ones, **B framed**
   (the map whole in a frame, the words beside it) only where neither fits. A style fits
   when its words, stamp and logo darken at most 3% of the map's lit-school pixels
   (measured on the picture: the bar allows a few halo pixels at a word's edge, never a
   school's dot under a line of text); the order is C, A, B for closings and districts and
   A, C, B for calm maps. When no style fits, no fresh card is made and the post goes with
   the library's dated card. The log says which style and why. Every word, number, place and time on
   the card comes from the picture's facts, never from Haiku: counts in the picture say "in
   this view", the country's total says "across the US", the chance is a number on the card
   (the map draws none). The alt text is built from the same facts and set on the image.

5. The last step prints the cards and `picture.json` as base64 lines of the render job's
   own log (`relay.py`), with their SHA-256 as the job's output. The post job reads that log
   with its `GITHUB_TOKEN` (`actions: read`), checks the lines' order, size and digest, and
   writes only the five known files. Anything wrong: the post goes with the library card.

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

If X refuses the refresh token, the stored token does not open, the rotated token cannot
be stored, or the token lacks a scope a post needs, the run opens one issue, **X posting
stopped: refresh token**, that says which, with the steps below, and records which secret
stopped; it never retries in a loop. Only an issue the workflow itself opened
(`github-actions[bot]`) is ever updated or closed: anyone can open an issue with that title
in a public repository, and the owner's steps never go into one a stranger wrote. When the
rotated token could not be stored, the run still posts the post it claimed with the fresh
access token, and ends red.

A scheduled run with nothing to post refreshes once only when the chain stopped and the
`X_REFRESH_TOKEN` secret is not the one that stopped (the owner pasted a new one): the new
token is checked and the issue closes, without waiting for a post. The same refused secret
is never tried again by itself.

### When the issue opens (the owner)

1. X developer console > the app of @SnowlightMap > **Keys and tokens** > OAuth 2.0:
   generate a new access token and refresh token (scopes: tweet.read, tweet.write,
   users.read, offline.access, media.write).
2. GitHub > Settings > Environments > **x-posting** > `X_REFRESH_TOKEN` > edit, paste the
   new refresh token, save.
3. Done: the next scheduled run (16:37 or 20:41 UTC), or a push to `social/queue/`, starts
   from it and closes the issue once it works with every scope.

### A claim a stopped run left

A run claims a post's slot in D1 before it sends anything. If the run stops mid-send (a
timeout, a cancelled job), the slot stays `claimed`: it may or may not be on the account,
so it is never sent again by itself, and every run warns: "queue:NNNN was claimed by run
... and never finished". Check @SnowlightMap. If the post is not there and should go,
delete the row (Cloudflare dashboard > D1 > `snowlight-live-state` > Console:
`DELETE FROM social_posts WHERE slot = 'queue:NNNN' AND state = 'claimed'`); the next run
posts it.

### Never drop the posts table

`social_posts` in D1 is the only record of what was posted. If it is dropped or the database
is made again, every file still in `social/queue/` posts again. Never drop it, and remove a
queued file from `social/queue/` once it is posted.

## Secrets (the owner adds them; never paste them anywhere else)

| Secret                                              | Where                      | What for                                                        |
| --------------------------------------------------- | -------------------------- | --------------------------------------------------------------- |
| `X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_REFRESH_TOKEN` | environment `x-posting`    | the X app and the first refresh token                           |
| `ANTHROPIC_API_KEY`                                 | environment `x-posting`    | Haiku's daily post (a dedicated key with a monthly spend limit) |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`     | repository (already there) | the D1 store                                                    |

The `x-posting` environment must be limited to the default branch, and only the owner can
set that (it has not been checked from here): GitHub > Settings > Environments >
**x-posting** > Deployment branches and tags > **Selected branches and tags** > add
`claude/keen-faraday-oy7yqw` only. Without it, a workflow pushed on any other branch of this
repository could name the environment and read the X secrets.

The Cloudflare token is a repository secret, so any workflow on any branch could rewrite the
`social_*` rows (it cannot open the sealed token, whose key comes from `X_CLIENT_SECRET`,
but it could break the chain). If the owner wants that closed too: make a Cloudflare token
with D1 edit rights only, add it as `CLOUDFLARE_API_TOKEN` (with `CLOUDFLARE_ACCOUNT_ID`) as
**environment** secrets of `x-posting`; the job then uses those over the repository ones.

The workflow has no trigger a
fork or pull request can fire (no `pull_request`, `pull_request_target` or
`workflow_dispatch`), checks the branch again in its first step, gives the secrets to the
post step alone, masks every token it derives, prints every line as one plain line that
no outside text (Haiku's answers, an error) can turn into a workflow command, writes nothing
to files, artifacts, caches or the step summary, pins its two actions by full commit SHA
and `uv` by version, and runs the browser in a job of its own. Its `log-check` job reads the
post job's own log and fails on any secret-shaped value or a command that stops masking. If a key ever leaks,
regenerate it in the X or Anthropic console and paste the new one.

## What the log shows

One line per step: what was picked and why, the token version stored, the post id and its
URL, the posted text. Never a token, a key, or an answer's body.
