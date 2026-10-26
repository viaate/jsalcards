# Posts on X (@SnowlightMap): runbook

`.github/workflows/social-post.yml` posts on the X account @SnowlightMap by itself: queued
posts written ahead, and once a day a short post Claude Haiku writes from the facts file.
Every post carries one real image and passes the same checks first. Code:
`pipeline/snowlight/social/`.

**To stop it:** Actions > **social-post** > **...** > **Disable workflow** (it works from
GitHub mobile). Deleting the workflow file or removing the X secrets from the `x-posting`
environment stops it too. Nothing else posts on the account.

## What posts, and when

- **Queued posts** (`social/queue/<NNNN>.json` and its image): a push to the default branch
  that changes `social/queue/` posts the oldest one not posted yet. The daily run posts one
  too if one is waiting. A queued post is posted at most once, ever.
- **The daily post**: the scheduled run at 16:37 UTC (late morning in the US). With nothing
  queued, `ANTHROPIC_API_KEY` set and nothing posted in the last 20 hours, Haiku
  (`claude-haiku-5-5`) writes one post, in turn a dev log and a "join the waitlist" post,
  from `social/facts.md`, the subjects of the commits since the last post, and one image it
  picks from `social/images/`. Without the key the run says "no Anthropic key" and posts
  only queued posts.

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

## The facts file and the images

`social/facts.md` is the only source of what a post may say. One fact a line, tagged
**LIVE** (true and running now), **TESTING** (built, but in practice mode or behind the
lock) or **COMING** (not on yet), with the words that name it. Keep it current: when
something ships, move its fact to LIVE in the same change. Nothing private goes in it.

`social/images/<id>.json` describes exactly what its image shows and the day it was taken;
Haiku picks by that description. Images are real screenshots of the real site with real
data, PNG or JPEG under 5 MB, never private screens (no admin view, no lock form).

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
4. uploads the image (`POST /2/media/upload`, scope `media.write`) and posts
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
