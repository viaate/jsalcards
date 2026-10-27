# Posts on X (@SnowlightMap): runbook

`.github/workflows/social-post.yml` posts on the X account @SnowlightMap by itself: queued
posts written ahead, and once a day a short post Claude Haiku writes from the facts file
(**switched off for now**: see "The Haiku writer's switch" below). Every post carries a
branded card made fresh from the real map at post time and passes the same checks first.
Code: `pipeline/snowlight/social/`.

**To stop it:** Actions > **social-post** > **...** > **Disable workflow** (it works from
GitHub mobile). Deleting the workflow file or removing the X secrets from the `x-posting`
environment stops it too. Nothing else posts on the account.

X asks that an account posting by itself carries its **Automated** label: on X, the
account's Settings > Your account > Account information > Automation, with the owner's
own account as the managing one.

## What posts, and when

- **Queued posts** (`social/queue/<NNNN>.json`): a push to the default branch
  that changes `social/queue/` posts the oldest one not posted yet. The daily run posts one
  too if one is waiting. A queued post is posted at most once, ever. A queued post marked
  `"fresh_only": true` (the first post, `0001`) goes only with a fresh card taken by the run
  that posts it, of a kind its `pictures` list allows; while no fresh card fits, it waits
  (the run ends red and says so) and holds the queue, and Haiku does not write in its place.
- **The daily post**: the scheduled runs at 16:37 UTC (late morning in the US) and 20:41 UTC
  (a second slot, in case GitHub drops or delays the first). With the Haiku writer switched
  on (below; it is **off** now), nothing queued, `ANTHROPIC_API_KEY` set and nothing posted
  in the last 20 hours, Haiku
  (`claude-haiku-5-5`) writes one post, in turn a dev log and a "join the waitlist" post,
  from `social/facts.md`, the subjects of the commits since the last post, and the run's
  fresh card with its description (the only facts about the picture it may use). Without
  the key the run says "no Anthropic key" and posts only queued posts. Haiku gets one try a
  UTC day: the run records the day in D1 (`social_haiku_days`) before its first call, so
  when that try fails (both drafts refused, X refuses the post, the run stops) the second
  slot asks Haiku nothing that day; it writes only when the first slot never reached Haiku
  (GitHub dropped it). The commit subjects Haiku sees leave out any with a digit, station
  call letters, a link or (while chances are TESTING) a word of a chance.

## The Haiku writer's switch

The first line under the title of `social/facts.md` switches the daily Haiku post:

```text
HAIKU_POSTS = off
```

It is **off** now. While it is off, only the queued posts in `social/queue/` go out, each
written and checked by the lead (starting with `0001`), and no run calls Anthropic at all,
even with `ANTHROPIC_API_KEY` set: a scheduled run posts the next queued post if one is due,
else nothing, and every run says "the Haiku writer is off" in its log. It is off because the
deterministic checks on Haiku's drafts get one more review round first: the last round found
drafts that still pass them while comparing Snowlight with other products in allowed words,
calling a not-live feature live, or claiming accuracy with "right". Queued posts are not
affected: the lead writes and reviews each one.

The run reads the line once, when it starts. Only one line `HAIKU_POSTS = on` switches the
writer on; no line, any other value, or two such lines leave it off. **To turn it on** (the
lead, once that round passes): change the line to `HAIKU_POSTS = on` in a commit on the
default branch, with `ANTHROPIC_API_KEY` in the `x-posting` environment (a dedicated key with
a monthly spend limit). The next scheduled run with nothing queued then has Haiku write, with
every cap below. Changing it back to `off` stops it the same way.

## Model first, and no one else

Two rules hold for every post, Haiku's and the queued ones alike, and for every card:

- **Model first.** Each post states one plain fact about the prediction model behind the
  chances, from the facts file's model section (the LIVE facts whose ids are `model` and
  `model-*`): that Snowlight's chances come from a real statistical model trained on real
  closing records, not a guess, and something concrete about it (the 2,388 real past school
  days it is trained on, how it leans on a district's own records and its county's, state's
  and region's, the weather service's winter alerts it sorts days by, the walk-forward test
  on past winters it never saw, a new set about every 30 minutes). Haiku is given one of
  them a day, in turn (`rules.model_fact_for`: seven LIVE model facts, so with the styles
  alternating each fact pairs with both), and the deterministic check refuses a draft that
  does not name it, or a post that names no model fact at all. A model fact that is TESTING
  (the forecast reasons, the night-before outlook, the watch raise) or COMING (learning from
  this winter's closings) is said as testing or coming, like any other. No accuracy number
  or score is ever posted: the past records lean toward big storm days.
- **No one else.** A post says what Snowlight does and never describes, names or compares
  other products, sites or people. Refused: any competitor's name, also run together or
  spaced out ("Snowday Predictor", "Snow-Day Calculator": names are matched on the text with
  spaces, hyphens and dots taken out), "snow day" or "snowday" followed by a product word
  ("snow day sites", "snow day trackers", "snow day apps", "snow day predictions"),
  "calculator(s)", "competitor(s)", "unlike", "other apps", "other sites", "other
  predictors", "other people", "most people", "folks", "the usual", "famous", "popular",
  "elsewhere", "out there", "the internet", "everyone else", "better than", "outperform",
  "outdoes", "superior", "more accurate", "most accurate", "AI" (also "A I"), "ML",
  "neural", "ChatGPT", "AI-powered", "machine learning", "formula", any "-er than" or "more
  ... than", "they guess", and "guess" in any form except "not a guess" (about Snowlight's
  own chances). Refused too: what others do or use ("instead of", "rivals",
  "alternatives", "the radar", "rumors", "vibes", "tricks", "weatherman", "the news", "TV"),
  any plural of a product word ("news sites", "TV stations", "weather apps"), uniqueness
  ("the first", "the biggest", "the largest", "unique", "unmatched", "one of a kind"), "SDC"
  however it is spaced or dotted ("S.D.C.", "S D C"), and any letter outside the Latin
  script or invisible character, so a name cannot hide behind a Cyrillic letter or a
  zero-width space. Haiku's second check is a second net, never the only one.

The A card's line on a dev log or waitlist card is the model line, "A prediction model
trained on real closing records, not a guess", words of the LIVE fact `model`. It names no
chance, so it stays while chances are TESTING (below).

## Chances while the site is locked

The site stays locked until the owner says its chances are ready, so a post never shows what
the site still hides. One switch decides it: the status of the `chances` fact in
`social/facts.md` (`rules.chances_shown`). While it is **TESTING** (now):

- the render job does not read the predictions, so the picture is never a district's chance
  view, and its description, card and alt text hold no chance at all (no number, percent,
  "chance" or "odds"); the A card's chance line is gone and its model line stays;
- `cards.py` refuses a card or alt text that holds any word of a chance, and the post job
  drops a fresh card whose picture, description or alt text gives one (the post then goes
  with the library card); the library refuses a card whose description or alt text gives one;
- the checks refuse any post that gives a chance: a percent sign, "percent", odds, "3 in 4",
  or a level next to "chance" ("a high chance", "chances are low", "near nothing"); a
  sentence may still say where the chances come from when it names a LIVE model fact ("each
  district's chance comes from a statistical model trained on 2,388 real past school days"),
  but only with no word that offers the chances to anyone ("see your district's chance",
  "the chances are up", "posted for every district", "already checking", "now", "you"), and
  Haiku is told the same;
- the facts file itself may hold no chance number (parsing it fails otherwise).

When the owner unlocks the site, the lead marks `chances` LIVE (with any numbers it should
give) and chance cards and posts come back with no code change.

## Closings while the reader is in practice mode

The same kind of switch holds closings back: the status of the `closings` fact
(`rules.closings_shown`). Until the lead marks it **LIVE** (the reader's finds are checked
before anything goes public, even once `LIVE_PUBLISH` is on for the locked site):

- the render job drops the closings file it read: the picture is never the closings view,
  the page is served a 404 for the file (as in practice mode, so no school glows), and the
  description says nothing of closings (not even "no school is lit up");
- `cards.py` refuses a closings picture and any card or alt text with a word of closings on
  the map ("closed", "closings", "delayed", "lit up", "glow"; the model's "closing records"
  and the reader's "closing lists" are not closings on the map); the post job drops a fresh
  picture or card that shows them, and the library refuses a card that does.

Marking `closings` LIVE brings the closings view and its counts back with no code change.

## Caps (in code, tested)

- At most **1 post a run**, **2 posts a UTC day** of every kind (the D1 claim that starts a
  post holds the cap, so two runs cannot both pass it), and **1 Haiku post a UTC day** (its
  record is named by the day).
- At most **4 Haiku calls a run** (write, check, and one more try of each), each capped at
  **1,024 output tokens**, effort `low`, and no SDK retries, and **one Haiku try a UTC day**
  (its D1 row is made before the first call), so at most 4 calls a day. An answer that says
  the key, the model id or the request is wrong (HTTP 400, 401, 403, 404) stops at once and
  the run ends red. A day's Haiku cost is a fraction of a cent.
- While posting is stopped (the refused token, or a post X refused for good, below), a run
  stops before anything else: no Haiku call, no claim, no refresh, no change to the issue.
  The stop holds even when the database could not record it (the open token issue carries
  the chain's version, and the run that could not record it ends red), and a hold whose
  issue could not be opened stays until its issue is opened and closed.
- A post X refuses twice in a row with the same 4xx (not a 429, not one that holds posting)
  is skipped for good, with an issue, **X posting: a post was skipped**; the other posts go
  on, and a skipped post counts toward no cap. A 429 or a 5xx is never counted.
- Each run logs every Haiku call's output tokens. When both of a day's tries run out at the
  1,024-token cap (Haiku 5.5 thinks first, and its thinking counts), the run ends red with a
  warning: the cap, not the draft, cost that day's post.
- X bills each post on the owner's prepaid credits. Keep the balance small and auto-recharge
  off: the most anything can ever spend is that balance.
- The spending limits are the owner's to set (nothing here can set them): in the X developer
  console, a spend cap (or a small prepaid balance with auto-recharge off) for the app; in
  the Anthropic console, a monthly spend limit on the dedicated key.

## Checks every post passes

`pipeline/snowlight/social/rules.py`, before anything is sent:

- at most 270 characters as X counts them; no URL, domain or @mention (the link is in the
  bio); at most one hashtag and one emoji; no `!!` and no em dash;
- a closed vocabulary: every word is a word of the facts file (a fact's text, terms or
  excepted phrases), of the picture's description, of the commit subjects Haiku was shown,
  a small word ("the", "and", "it") or one of the plain words of my voice in
  `rules.VOICE_WORDS` ("dev log", "built", "fixed", "spent", "night", "join", "link",
  "bio"), in any plural, past or -ing form; a hashtag only from `rules.HASHTAGS`. So no post
  can name or describe anything the facts do not ("SDCalc", "influencers", "online",
  "industry-leading", "gold standard"), claim accuracy in new words ("results",
  "confident"), invent a feature, a hire, a partner or a user ("iPhone", "hired",
  "partnered", "a bunch of you"), or give a level or a place ("could close", "the
  Rockies"). Haiku is told the same list. The other checks below still hold for the words
  the facts do give;
- it names a LIVE model fact, and a Haiku post the day's (above);
- no banned words: hype ("most accurate", "revolutionary", "AI-powered", "guaranteed",
  "never wrong", "better than"), other calculators or sites by name, "SDC", "formula",
  "reconstruction", station call letters;
- hype and comparisons as whole words: "best", "only", "unlike", "vs", "precise",
  "perfect", "spot on", "number one", "other apps", "others", "AI"; and every comparison
  with, or description of, anyone else (above);
- "you can now", "check your school", "see your district", "find it on", "available now"
  and the like only of the waitlist or worded as coming: nobody can open the map before
  launch;
- no accuracy claim, with or without a number ("always right", "called most snow days
  right", "hit rate", "reliable", "correct", "track record", "rarely wrong", "proven", "it
  works", "held up", "scored well", "precision", "count on", "science-backed"), nothing the
  facts do not say of the product or its maker ("download", "the Snowlight app", "free",
  "schools use", "trusted by", "love", "we", "our team", "investors", "backed by", "daily
  emails", "never shared", "growing"), no hype words ("huge", "massive"), no school, district
  or person by name ("... Public Schools", "Lincoln High's", "... ISD", "my friend Jake"), no
  state the picture's description does not name, and no run-together word of letters and
  digits the facts do not hold ("v3");
- every number, in digits or in words ("fifty", "twenty-four", "first"), is in
  `social/facts.md` in the same form and used as the facts use it: a word near it is near it
  in the facts too, the word right after it (its noun) is among the facts' first three after
  it, and a number in digits shares a word before it in its sentence with the facts' own
  sentence ("24/7 in practice mode" passes, "24 schools" does not, nor "11 states" from "11
  past winters", "661 snow days" from "661 real past private school days", or "the reader
  checks 118,211 schools" from "the directory holds 118,211 schools"). A number from the
  picture's description is never written in a post: the card carries every count, time and
  chance, labeled;
- "tomorrow", "next week", a weekday or a month only as the facts or the picture's
  description use them; never a launch date;
- each TESTING or COMING thing a post names (by its terms, such as "closings", "closed",
  "alerts", "text", "the map", "search") is said to be testing or coming by a word said of
  it, in its own clause only (commas, semicolons, colons, dashes, "but" and "and I" part
  clauses): next to it, or as near to it as to anything else not live in that clause, with
  any other thing between them only as an item of one list or a place phrase ("phone alerts
  and closings are coming", "closings on the map start this winter"), never across a verb
  ("closed schools glow and phone alerts are coming" is refused); or as a clause of its own
  holding nothing but the not-live words right after ("Every school closing on one map,
  coming this winter"); or, for a TESTING thing only, as "testing it" or "testing them"
  later in the sentence ("and I will keep polishing it" covers nothing). A word about one
  thing never covers another ("Phone alerts are coming; closed schools glow" is refused for
  the glow), "more coming" covers nothing, a COMING thing is only "coming" (never "in
  testing" or "in practice"), and "practice" covers only the reader's practice mode.
  "Already", "works", "is on", "turned on" or "ends" next to such a thing refuses it
  outright. A sentence that names one holds no live claim ("is live", "shows up", "ships",
  "works for everyone", "public now") and no end of testing ("no longer", "done testing",
  "practice is over", "left testing", "graduated from testing", "out of beta"); a live claim
  that names no LIVE fact ("Snowlight is live") is refused too. "You can ..." is said only
  of the waitlist or as what people will do ("at launch you can search"): a testing word
  never covers it ("you can search by ZIP code while I keep testing" is refused);
- while chances are TESTING, no chance in other words either: "a coin flip", "near
  certain", "probably", "likely", "could", "might", "looking", "expects", "watching", "per
  the model" near a closing word, or "up", "down" or "hot" near "chance"; and never a place's
  chance ("Denver's chance");
- no more email than the waitlist fact gives (one email at launch): never "emails" or "an
  email every morning";
- a picture that is not current (a library card, or a fresh one of a stale closings file) is
  never called current: no "now", "today", "tonight", "currently", "as of", "just",
  "fresh", "latest" or clock time;
- a waitlist post, and any post that names the waitlist, says "link in my bio".

A Haiku post also goes past a second Haiku call that checks it against the facts and
answers `{ok, problems}`. Either check failing gives one more try with the problems shown;
a second failure means no post that day (the run log says why, and the day's D1 row keeps
the second slot from asking again). A queued post that fails the checks is never sent and
turns the run red.

## The facts file

`social/facts.md` is the only source of what a post may say. One fact a line, tagged
**LIVE** (true and running now), **TESTING** (built, but in practice mode or behind the
lock) or **COMING** (not on yet), with the words that name it (`| terms: ...`) and the
phrases that hold one of those words but name another fact (`| except: ...`, such as
"closings reader", the LIVE reader, for the COMING closings on the map). Keep it current:
when something ships, move its fact to LIVE in the same change. Nothing private goes in
it. Every number in the model section comes from docs/predict.md and the committed model
file, and a test checks them against both. A term is a word or phrase, never a bare number
(a term "2,388" would split at its comma). A line printed on a card (the A card's "A
prediction model trained on real closing records, not a guess", the B card's "Building
Snowlight") must be words of a LIVE fact; a test holds the templates to it, and a library
card's line is kept in its JSON (`tagline`): when that line leaves the facts file (it must
stay words of a LIVE fact, or the whole text of a COMING one), the run stops red until the
library is made again with `snowlight social render --fallback`.

## The picture: a fresh card at post time

The workflow's **render** job makes every post's picture fresh (`snowlight social render`,
`render.py`). It runs on its own machine with no secret, no environment and read-only
repository access, and writes no cache, because its browser reads the live site and a third
party's map tiles; the secrets live only in the post job, which runs no browser. The browser
reaches only snowlightmap.com, viaate.github.io (the live files) and tiles.openfreemap.org:
every other request is aborted and its host said in the log, every WebSocket gets a
stand-in that reaches no server (the site opens none), and WebRTC is kept off direct UDP. It runs in Chromium's own
sandbox (the job first allows the unprivileged user namespaces that sandbox needs on Ubuntu
24.04); if the runner still cannot start it, the log says so in a warning and the browser
runs without it, still reaching only those hosts. The card pages it lays out next reach no
network at all:

1. Headless Chromium (installed in the job) reads the site's lock check from its own page and
   unlocks it in that browser only (never printed). Signed out, it opens the map at a view
   where the site reads the school directory and `live/closings.json`, and keeps their bytes;
   it reads `predictions/latest.json` from the same live root, only while the facts file
   marks chances LIVE.
2. `picture.py` picks the view from those files: the busiest picture-sized area of lit
   schools when closings light any today; else, only while chances are LIVE, the district
   with the highest chance of no school (at least 10%), framed by its schools on the left;
   else the dark national map (the
   words never say "night": the map is dark at any hour). It writes the description (time
   with its zone, place by state, counts, chance) and the same facts as fields. Nothing is
   said about closings when the closings file was a 404 (practice mode), and neither when it
   is older than 20 minutes: a stopped reader's empty file is no sign that nothing is
   closed, so that picture is not current and the post may not call it so. A chance is shown
   only from a predictions file at most 90 minutes old, and only for the next school day not
   yet under way: the first of the file's days whose 5 AM, in each district's own time zone,
   is still ahead in most districts (at 11:27 AM Central on a Monday the card names Tuesday).
   No district is named.
3. It opens that view served exactly those files, hides every piece of the site's interface
   with a style in that page only, waits until the map is at rest (twice), checks that the
   map lit as many schools as the description counts at the zoom asked, and takes a
   1600 x 900 picture of the map alone.
4. `cards.py` lays the Snowlight card over it for each kind of post (`dev-log`, `waitlist`)
   from three templates in `pipeline/snowlight/social/cards/` (the site's Geist fonts, OFL):
   **C stamp** for closings and chance pictures, **A broadcast** for calm ones, **B framed**
   (the map whole in a frame, the words beside it) only where neither fits. A style fits
   when its words, stamp and logo darken no lit school's centre (every lit school in view is
   measured where the picture puts it, one by one) and at most 3% of the map's lit-school
   pixels (the halos' edges); the order is C, A, B for closings and districts and A, C, B
   for calm maps. The A card's model line is checked against the run's facts file when the
   card is laid: if the lead rewords or demotes the `model` fact, A no longer fits and the
   card takes another style. On a closings picture the A card's status counts say "in this
   view", like C's and B's. When no style fits, no fresh card is made and the post goes with
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
2. refreshes with the stored refresh token, or starts the chain from its secret (below) when no
   token is stored yet or the secret is newer than the stored chain (the row keeps a keyed
   fingerprint of the secret the chain started from, so a newly pasted secret is noticed).
   The secret is the OAuth 1.0a pair `X_ACCESS_TOKEN` and `X_ACCESS_TOKEN_SECRET` when both
   are set: the run exchanges it once for an OAuth 2.0 token pair (`POST /2/oauth2/token`,
   grant `urn:ietf:params:oauth:grant-type:token-exchange`; for an app with Read and write
   permission X grants every write scope, `media.write` among them, and a refresh token),
   and never again for the same pair, since a new exchange ends the pair the one before
   gave. Otherwise it is `X_REFRESH_TOKEN` (X's console generator gives that token no
   `media.write`, so no image can go up with it). A refused exchange stops the chain like a
   refused refresh token; an exchange with no answer posts nothing and the next run
   exchanges again;
3. stores the new refresh token right away, sealed with AES-256-GCM under a key derived
   (HKDF-SHA256) from `X_CLIENT_SECRET` and bound to the row and its new version (an older
   sealed value written back does not open), with `UPDATE ... WHERE version = <read> AND
lease = <this run>`: the version goes up by one, and a run that lost the row stores nothing
   (the chain is then lost, and the run says so and opens the issue);
4. uploads the card (`POST /2/media/upload`, scope `media.write`), sets its alt text
   (`POST /2/media/metadata`; the post goes without it if X refuses) and posts
   (`POST /2/tweets`), recording the post id in D1.

The lease runs from when it is taken, and no refresh starts later than 6 minutes into the
Post step (whose timeout is 10), so a refresh and the store of its rotated token always
finish before the step can be killed.

If X refuses the refresh token, the stored token does not open, the rotated token cannot
be stored, or the token lacks a scope a post needs, the run opens one issue, **X posting
stopped: refresh token**, that says which, with the steps below, and records which secret
stopped. From then on every run stops before it picks anything while `X_REFRESH_TOKEN` is
still that secret: no Haiku call, no claim, no refresh, and the issue is left as it is. The
issue's body ends with a hidden line naming the stored chain's version when it stopped and
the first 12 hex characters of the keyed fingerprint of the refused secret (an HMAC under
`X_CLIENT_SECRET`: nothing that can be turned back into a token): if the database could not
record the stop, the run ends red, and every later run still stops while that issue is open,
the chain is at that version and `X_REFRESH_TOKEN` is still that secret, also when it was a
newly pasted secret that X refused too. When an earlier refresh got no answer (a timeout or
a 5xx), the row records it, and a later refusal of that token says in the issue that the
lost refresh most likely spent it; the owner's steps are the same. A 429 or another answer
that says X did not take the refresh records nothing: the next run simply tries again. A
GitHub answer that is not JSON (an error page) is one warning line, and the database
decides. Only an issue the workflow itself opened
(`github-actions[bot]`) is ever updated or closed: anyone can open an issue with that title
in a public repository, and the owner's steps never go into one a stranger wrote. When the
rotated token could not be stored, the run still posts the post it claimed with the fresh
access token, and ends red.

A run whose secret (`X_REFRESH_TOKEN`, or the `X_ACCESS_TOKEN` pair) is not the one that
stopped (the owner pasted a new one) starts from it: a run with a post sends it, and a scheduled run with nothing to post
refreshes once, so the new token is checked and the issue closes without waiting for a
post. The same refused secret is never tried again by itself.

### When X refuses a post (the owner)

When X refuses a post or its image upload for good (HTTP 401, 402 or 403: no credits, no
write permission, a duplicate), the run opens one issue, **X posting stopped: X refused the
post**, with X's status and what it means, and holds posting: every run stops before it
picks anything while that issue is open and the chain's secret (`X_REFRESH_TOKEN`, or the
`X_ACCESS_TOKEN` pair while both are set) is unchanged. Fix the cause (add credits; give
the app Read and write permission and set a new `X_ACCESS_TOKEN` pair; delete a duplicate's
queue file), then close the issue: the next run tries once more and opens it
again if X still refuses. A post that goes out closes it. The hold keeps the number of the
issue it opened: if GitHub would not open the issue, the hold stays (never lifted as if the
owner had closed it), every run tries to open it again and ends red, and nothing is sent
until it is opened and then closed.

Any other refusal of a post (a 400, a 413) drops the claim once, and a later run tries
again; a second refusal in a row with the same status skips that post for good (`skipped`
in `social_posts`, the count in `social_refusals`, where each run counts once even when its
answer was lost and the count was sent again) and opens **X posting: a post was
skipped**: fix the file and give it a new id, or delete it, then close the issue. A 429 or a
5xx is never counted.

### When the issue opens (the owner)

1. X developer console > the app of @SnowlightMap > **Keys and tokens** (permission **Read
   and write**) > OAuth 1.0 Keys > Access Token (for @SnowlightMap) > **Generate**.
2. GitHub > Settings > Environments > **x-posting**: set `X_ACCESS_TOKEN` to the Access Token
   and `X_ACCESS_TOKEN_SECRET` to the Access Token Secret, save. (Pasting a new
   `X_REFRESH_TOKEN` instead works only while the pair is not set, and X's console gives that
   token no `media.write`.)
3. Done: the next scheduled run (16:37 or 20:41 UTC), or a push to `social/queue/`, starts
   from it and closes the issue once it works with every scope.

### A claim a stopped run left

A run claims a post's slot in D1 before it sends anything. If the run stops mid-send (a
timeout, a cancelled job), the slot stays `claimed`: it may or may not be on the account,
so it is never sent again by itself, and every run warns: "queue:NNNN was claimed by run
... and never finished". Check @SnowlightMap. If the post is not there and should go,
delete the row (Cloudflare dashboard > D1 > `snowlight-live-state` > Console:
`DELETE FROM social_posts WHERE slot = 'queue:NNNN' AND state = 'claimed'`); the next run
posts it. When a run posted but could not record it (it asks D1 three times), its log says
"queue:NNNN is posted as <post id>, but its record stays claimed": mark it posted
(`UPDATE social_posts SET state = 'posted', post_id = '<post id>' WHERE slot = 'queue:NNNN'`).

### When X's answer does not confirm a post (the owner)

Only an HTTP 201 whose answer holds the post's id records a post. When the post request went
to X and no such answer came (no answer at all, a 5xx, or any other 2xx: a 200, 202 or 204,
or a 201 without the id), X may have made the post, so it is never a refusal: the slot stays
`uncertain` in `social_posts` and no run sends it again by itself, the other posts go on, the
run ends red and it opens (or brings up to date) one issue, **X posting: check whether a
post went out**. Check @SnowlightMap. If the post is there, record it
(`UPDATE social_posts SET state = 'posted', post_id = '<its id>' WHERE slot = 'queue:NNNN'`);
if it is not and should go, delete its row
(`DELETE FROM social_posts WHERE slot = 'queue:NNNN' AND state = 'uncertain'`) and the next
run posts it. Then close the issue. Every such post:
`SELECT slot, claimed_at FROM social_posts WHERE state = 'uncertain'`.

### Never drop the posts table

`social_posts` in D1 is the only record of what was posted. If it is dropped or the database
is made again, every file still in `social/queue/` posts again. Never drop it, and remove a
queued file from `social/queue/` once it is posted.

## Secrets (the owner adds them; never paste them anywhere else)

| Secret                                              | Where                      | What for                                                         |
| --------------------------------------------------- | -------------------------- | ---------------------------------------------------------------- |
| `X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_REFRESH_TOKEN` | environment `x-posting`    | the X app and the first refresh token                            |
| `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`           | environment `x-posting`    | the account's OAuth 1.0a pair, exchanged once to start the chain |
| `ANTHROPIC_API_KEY`                                 | environment `x-posting`    | Haiku's daily post (a dedicated key with a monthly spend limit)  |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`     | repository (already there) | the D1 store                                                     |

The `x-posting` environment must be limited to the default branch, and only the owner can
set that (it has not been checked from here): GitHub > Settings > Environments >
**x-posting** > Deployment branches and tags > **Selected branches and tags** > add
`claude/keen-faraday-oy7yqw` only. Without it, a workflow pushed on any other branch of this
repository could name the environment and read the X secrets.

The Cloudflare token is a repository secret, so any workflow on any branch could rewrite the
`social_*` rows (it cannot open the sealed token, whose key comes from `X_CLIENT_SECRET`,
and an older sealed value written back does not open, but it could break the chain: the
run then opens the issue). If the owner wants that closed too: make a Cloudflare token
with D1 edit rights only, add it as `CLOUDFLARE_API_TOKEN` (with `CLOUDFLARE_ACCOUNT_ID`) as
**environment** secrets of `x-posting`; the job then uses those over the repository ones.
The poster sends the Cloudflare token to `https://api.cloudflare.com` only: no setting, in
the environment or anywhere else, points it at another host.

The workflow has no trigger a
fork or pull request can fire (no `pull_request`, `pull_request_target` or
`workflow_dispatch`), checks the branch again in its first step, gives the secrets to the
post step alone, masks every token it derives, prints every line as one plain line that
no outside text (Haiku's answers, an error) can turn into a workflow command, writes nothing
to files, artifacts, caches or the step summary, pins its two actions by full commit SHA
and `uv` by version, and runs the browser in a job of its own. Its `log-check` job reads the
post job's own log, also of a post job that was cancelled or timed out after it started,
and fails on any secret-shaped value or a command that stops masking (a post job cancelled
before it started has no log, which it says). If a key ever leaks,
regenerate it in the X or Anthropic console and paste the new one.

## What the log shows

One line per step: what was picked and why, the token version stored, the post id and its
URL, the posted text. Never a token, a key, or an answer's body.
