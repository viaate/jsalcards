# The status page

`https://status.snowlightmap.com` is a page anyone can open to see, in plain words,
whether Snowlight works right now and how it has done over the last 90 days. It
looks at four parts:

- **Website**: opening snowlightmap.com.
- **Live school closings**: the closings and delays on the map.
- **Snow-day chances**: each district's chance of no school.
- **Accounts**: signing in and saved schools.

The line under each part's name says only what the part is. How it is doing is the
word beside it, so the page never shows "Not working" next to a sentence that says
all is well.

It is laid out like GitHub's status page (its layout and feel only: the code, words and
drawings are ours). At the top, one solid bar in the color of the worst state says it
in a few words ("Everything is working.", "Something is not working.") with when the
last check was; a screen reader is told which parts, by name. Under it, one card holds
the four parts (two to a row on a wide screen): each part's name with a small mark
whose tip says what the part is, **Working**, **Slow or late**, **Not working** or
**Could not check** on the right in that state's color, then 90 thin bars, one for
each day, with "90 days ago", the share of the checks that gave an answer and found
it working ("99.9% of checks working"), or in its place why there is none ("Could
not check"), and "Today" under them (on a narrow phone the share takes a line of its
own under the rule); the two parts that are files also say how long ago they were
updated. A day before the checks began, or one whose first check is not due yet, is
a light grey bar, so every row is whole; a day with too few checks to say is a darker
grey ("Not checked" in the key, the tips and the list alike), and the footer has a key
to every color. Pointing at a bar, or tapping it, shows that day in a tip under it.
Each bar is a day on the world clock, so its tip names the span it covers in the
reader's time zone ("Nov 1, 7:00 PM to Nov 2, 7:00 PM EST: not working for 15
minutes."), and a tip never names a date that "Past problems" uses for another span;
a reader whose clock is the world clock sees the bar's own day ("Mon, Nov 2").

Below the card, "Past problems" lists only the problem days among the days in the
reader's time zone from today back 15 days, never a day before the checks began,
newest first. No line gives the date the checks began. A day with no problem shows
nothing at all, today too: no date and no line (the owner's ruling of Nov 12: "only
show problem days"). When no day in the 90 has a
problem, "Past problems" is not drawn at all, and nothing anywhere says there were
none. Under each date are the problems
that covered any of it: in full on the day each began (an open one in full under
today, and "from" its time on the day it began), and as "still not working from the
day before" on each day after, until the time it ended. Three or more problems of one
part and one kind that began and ended on the same day are one line ("Accounts: slow
or late 48 times, 4 hours in all.", from the first to the last), so a part that flaps
does not fill the list. A gap is never let look like a quiet day: a day is left out
only when every part was checked on it and every bar of trouble it touches is one of
the problems listed. Otherwise it is listed with a note in place of problems: a day
with no checks says "Not checked.", a day partly checked says "This day was not
checked in full.", and, since the summary holds the newest 100 problems only, a day
whose bars show trouble no listed problem covers says "Some problems from this day
are not listed." (and the list says it holds the newest 100). Once the checks are
late, every check due since the last one counts as one with no answer: the day of the
last check says "This day was not checked in full." (after its problems, if it had
any) once that passes the allowance, and each day since says "Not checked."; before
that, a day after the last check is not listed, as its first checks are not due yet. Today, while a part could not be checked just now,
says "Not every part could be checked.".

"Partly checked" is counted in the reader's own day, never from a bar's color alone (a
bar is drawn working once half its checks gave an answer). The summary carries, for
each part, the runs of checks that gave no answer (a "Could not check" reading, or a
tick the checker did not take): the first such tick and how many in a row, for the 90
days, at most 300 runs a part (past that the oldest go, and `since` moves up). So the
page counts each part's checks with no answer inside the reader's day itself. The
allowance is a count, not a share: a day says it was checked in full only while every
part has at most 2 checks (10 minutes) with no answer on it; from 3 on it is listed as
"not checked in full". The same count is said on a day with problems: after its
problems it adds "This day was not checked in full." (joined to "Some problems from this
day are not listed." when both apply), unless one of its lines already says the checks
stopped. A day every part of which had no answer all day says "Not checked.". The
store shows no routine misses: on Nov 11 and 12 the website, the closings and the
accounts answered every check (115 of 115, then 288 of 288), and the chances' 31
unanswered checks on Nov 11 were one block of about 2.5 hours, so that day reads "not
checked in full".

Before the runs begin (`since`), the store kept only one count a part a UTC day. There
the page claims only what those counts prove: of a UTC bar's checks with no answer,
those that cannot all fit in the part of the bar outside the reader's day. A gap the
page cannot place is never said, so a reader's day checked in full is never marked
for its neighbour's gap (before the runs were kept, the page marked both days that
share a UTC bar). A summary with no runs at all, as every summary written before them
was, is read the same way. The checker makes the runs once from the samples it keeps (90 days) on its
first tick after the change, so the live page counts exactly from then on. When the
checks stopped while a problem was going on and stayed away past the reader's
midnight, each day they stayed away on with more than 2 checks with no answer says
what they last found ("Live school closings: not working when our checks stopped on
Nov 1, 10:15 PM EST. This day was not checked in full."), never left out as quiet.
The problem days before the 15, and the days among them not checked in full, are
behind a button that counts the lines it shows ("Show 3 earlier problems"): each
problem line of those days, and each of those days listed for its gap alone. A problem
that runs over several of those days has a line on each and is counted for each, and
one still going on today is counted only for its lines behind the button, never for
its line under today. With no problem day in
the 15 days, "Past problems" is that button alone. If the history could not be loaded, the list
says "The history could not be loaded. Reload the page to try again." (the one
thing to do, said once: the banner says only "We cannot load the status."), and each row
is an empty dashed outline the height of its bars with "Not loaded" under it, in no
color of the key, so it is never read as the days before the checks began. While the
page waits for its first answer neither "Past problems" nor the footer is drawn, so
the list takes its own size when it comes and nothing moves. A day or a stretch the checker
did not run is shown as not checked, never as working. The day the checks began
reads "working since checks began", not "working all day". The last bar is always
today on the world clock: if the checker has been silent for days, the bars for
those days read "not checked" and no old day is called today. In the first minutes
of a new day on the world clock, before its first check is due, today has no bar
yet and reads "not checked yet".

While a part's newest check could not tell, an open problem's length stops at its
last reading.

A part the checker has not once been able to read says "Could not check" under its bars.
That is what **Snow-day chances** says on the first day, until the chance job has
put its stamp on the host (its next run after this lands); the top of the page
then reads "We could not check everything." When the last check is old, the page
says so at the top, lists only problems of the 90 days its bars show, and says
nothing of the time since.

No line breaks inside a part's name, a date, a time or a count ("Live school
closings", "Snow-day chances", "at least", "Nov 10", "2:35 PM EST", "5 minutes"): they
are tied in the words themselves (`page/src/copy.ts`, `page/src/view.ts`), so it holds
in every typeface. A length of two parts ("23 hours 55 minutes") is one box of two:
where very large text makes it wider than the line, it breaks between its parts,
never between a number and its unit. `scripts/shots.cjs` checks every visible text at
nine widths, at text of 100%, 150% and 200%, in every state.

Whatever sits side by side (the banner's two lines, the parts) asks how
much room the page has in text units, not how wide the screen is, so with larger text
a tablet lays out like a phone. The side gutters stay 16 px at every text size.

The page and its history live on Cloudflare, apart from GitHub. So the page stays
up, and the checker keeps recording, when the website (GitHub Pages) or the
workflows that fill it (GitHub Actions) are down. That is the point of it.

The page uses no cookies, keeps nothing about its visitors, and loads nothing from
anyone else. Until you say it may be found, it asks search engines not to list it.

## What it costs

Nothing. It runs on the free plans of the Cloudflare account you already have: a
Pages project for the page, a Worker that checks every 5 minutes, and a small D1
database. Its day uses about 3,600 of the account's 100,000 free requests when
1,000 people open the page, and about 2,300 of the database's 100,000 free row
writes. That daily request limit is shared: the accounts (`snowlight-api`) and the
timer that starts the live closings and the chance job (`snowlight-timer`, docs/live.md)
count against the same 100,000. It would take about 33,000 loads of the status
page in one day to reach it; the page would then say it cannot load until midnight
UTC, and accounts would stop answering until then too. Nothing is ever charged.

## What you do once

### 1. Let the token manage Pages (only if it cannot yet)
Do this when the newest Status run is red and its message (on the run's page, under **Annotations**) says "The Cloudflare token cannot manage Pages". To look:
open the repository on GitHub, press the **Actions** tab, pick **Status** in the list on the left and open the run at
the top. A green run means the token already can: skip to step 2.
1. Go to <https://dash.cloudflare.com/profile/api-tokens> (or: your profile icon, top right > **My Profile** > **API
   Tokens**).
2. Find the token you made for Snowlight (**Edit Cloudflare Workers** unless you renamed it). Press the three dots at
   the end of its row > **Edit**.
3. Under **Permissions**, look for a row **Account / Cloudflare Pages / Edit**. If it is there, go to point 5.
4. If not: press **+ Add more**, set the new row to **Account** / **Cloudflare Pages** / **Edit**, then
   **Continue to summary** > **Update token**. The token itself does not change, so nothing changes on GitHub. (If
   Cloudflare does show you a new token, put it in the GitHub secret `CLOUDFLARE_API_TOKEN`, as in docs/accounts.md.)
5. Open the repository on GitHub, press the **Actions** tab, pick **Status** in the list on the left, press **Run
   workflow** (a grey button on the right), leave the branch as it is, and press the green **Run workflow**. It takes
   about five minutes.
   If that run is red again with the same message, the token GitHub uses is a different one: send us the run's
   message (under **Annotations**).

### 2. The one DNS record
The first time, wait for our word that the page has passed its checks at the `.pages.dev` address.
1. Open the repository on GitHub, press the **Actions** tab, pick **Status** in the list on the left, open the run
   at the top and scroll down to **Annotations**. A run prints two or
   three notices there. The one you want starts "The status page is live at" and goes on "add this DNS record at
   GoDaddy: type CNAME, name status, value …". Copy only the value: the one name that ends in `.pages.dev` (most likely
   `snowlight-status.pages.dev`), without `https://` and without the words in brackets after it:
   copy `snowlight-status.pages.dev`, not `(docs/status.md, step 2)`.
2. Sign in at <https://www.godaddy.com>, open **My Products**, find **snowlightmap.com** and press **DNS**.
3. Press **Add New Record**. **Type**: CNAME. **Name**: `status`. **Value** (GoDaddy may call it **Points to**): what
   you copied. **TTL**: leave it. Press **Save**. Change nothing else: the website and email records stay as they are.

### 3. Only if the Status run says it could not attach the name
At <https://dash.cloudflare.com>: **Workers & Pages** > **snowlight-status** > **Custom domains** > **Set up a
domain**, type `status.snowlightmap.com`, press **Continue**. If Cloudflare then shows a CNAME record for `status`
ending in `.pages.dev`, that is the record of step 2: confirm. If Cloudflare offers to move your domain or its
nameservers to Cloudflare, do not. Choose the option that keeps your DNS where it is (a CNAME record). Anything else:
stop and send us what the screen says.

### How to tell it worked
Wait 15 minutes (it can take an hour), then open <https://status.snowlightmap.com>: you see the status page, with a
padlock. Or run **Status** again (the **Actions** tab > **Status** > **Run workflow** > the green **Run workflow**,
as in step 1, point 5); on that run's page, under **Annotations**, a notice says
"https://status.snowlightmap.com is live." Still not
there after an hour: run **Status** once more (every run asks Cloudflare to look at the record again)
and send us its notice. An error page with the number 522 means step 3 is still to do. Until then the same page is
at the `.pages.dev` address.

## What a Status run tells you

Every run of **Status** (the repository's **Actions** tab, **Status** in the list on the left) prints one notice about the checker (on the
run's page, under **Annotations**), whether the rest of the run is green or red, even when the
checker's own deploy failed. If the run could not find the database, the notice says the store
could not be read:

`status checker: 36 of the last 36 checks kept (3 hours), 288 of the last 288 (24 hours); last at 2026-11-11 14:05 UTC: website ok 200, closings ok 200, chances ok 200, accounts ok 200; largest closings file 318 bytes.`

The first two numbers say how many of the 5-minute checks were kept. A few missing
is normal. In the checker's first 3 hours the first number is low, and in its first
day the second is: that is normal too. Under 34 of 36 once it has run 3 hours, or under
280 of 288 once it has run a day: send us the line. After the first morning with
many closings, run **Status** once and read the line again: the largest closings file shows how big the file got, and the first
number shows whether the checker kept up with it. Under 34: send us the line.

A red run that says "The Cloudflare token cannot manage Pages" is step 1 above.
The checker is already running and keeping history by then; only the page waits.

## How it fits together (for whoever works on it next)

Everything is in `status/`, and `.github/workflows/status.yml` tests and deploys
it. A change under `status/` starts that workflow and neither CI nor the Preview.

| Part | On Cloudflare | Code |
|---|---|---|
| The page | Pages project `snowlight-status`: static files and one Function, `GET /api/status` | `status/page/` |
| The checker | Worker `snowlight-status-prober`: cron `*/5 * * * *`, no URL | `status/prober/` |
| The store | D1 database `snowlight-status`, bound as `DB` in both | `status/prober/migrations/` |
| | Pure code both use | `status/shared/` |

**The probes** (`prober/src/probe.ts`, `shared/judge.ts`). Each tick asks each part
once, and once more 1.5 s later on trouble; the second try stands. A request
waits 8 s at most. A check that fails (no answer, a timeout, HTTP 429) is "Could
not check", never "Not working".

One answer that is not 200 from the data host for a file part is "Not working" at
once, not "Could not check" until a second in a row (lead's question, Nov 11; decided
with the store's numbers that night). In the store's first 107 ticks the two file
parts gave 183 readings with an answer and one was "Not working": a single chances
tick at 15:15Z on launch day, while the stamp was being put on the host. That is no
case for a rule that would hide every outage's first 5 minutes, and a file the host
will not serve is what visitors get too: it is the part not working, not the checker.
The checker's own failures (no answer, a timeout, 429, Cloudflare's refusal, no stamp
yet) were already "Could not check", and a 5xx or no answer already gets a second
try 1.5 s later. Revisit if the store shows single-tick file failures that the map's
visitors did not see.

- **Website**: `HEAD https://snowlightmap.com/`, the status code only. 200 within
  3 s is working, a slower 200 is slow, anything else is not working. No page is
  fetched, kept or shown.
- **Accounts**: `GET` of the accounts API's `/v1/health`, which must answer 200
  with `{"ok":true}`. The address is the one the API workflow finds; the checker
  carries the flag `global_fetch_strictly_public` so that Cloudflare lets one
  Worker ask another by its public address. An answer that reads as Cloudflare's
  own refusal (error 1042) is "Could not check". Any other answer that is not 200
  is "Not working", for every part. Not yet known: whether a connection the checker
  itself could not make ever comes back as a Cloudflare-made answer (codes 520 to
  530) and not as no answer. The store notice prints each part's last code. If one
  of those codes shows for a part that works when checked by hand, give those
  answers the same reading as 1042 in `shared/judge.ts`.
- **Live school closings**: `GET {live root}live/closings.json`. The file's own
  `generated_at` is its age: over 15 minutes is late, over 60 is not working, less
  the CDN's `Age` (10 minutes at most). Of the body only that instant and the
  body's length are kept; a file over 65,536 bytes gives its instant from its last
  bytes.
- **Snow-day chances**: `GET {live root}predictions/stamp.json`, never the chances
  file, which is megabytes. The stamp is about 80 bytes: the file's `generated_at`
  and its count of districts, put beside the file in the same commit by every
  upload of the chance job and by `predict blank` (`predict/publish.py`,
  `stamp_file`; docs/predict.md, "The two watches and the one issue"). Over 45
  minutes is late, over 90 is not working, and so is a stamp of no districts. No
  stamp on the host (404) is "Could not check". Whoever reverts or removes the
  stamp's writer deletes `v1/predictions/stamp.json` and
  `v1-shadow/predictions/stamp.json` from the live host in the same step: a stamp
  left behind would age into a false "Not working". The stamp and the file go up
  in one commit on the GitHub host, so one is never newer than the other. A host
  that writes files one at a time would write the stamp first; if the chances ever
  move to such a host, write the file first, so that a failure between the two
  leaves a stamp that is too old (late, and put right by the next pass), never one
  that says a file is fresh when it is not.

**A tick** (`prober/src/tick.ts`) reads what the store holds (the 90 days' counts,
the open problems, and the newest 103 closed ones, each by an index, so a part that
goes wrong and right for weeks never makes a tick read the whole table), probes
the four parts together, and writes the sample, the day's counts, the problems it opened or
closed and the summary in one D1 batch, which is one transaction. A tick is taken
in once. A run Cloudflare ends writes nothing, and that tick shows as no readings.
Two runs can overlap when one is slow. The batch's first write is a compare-and-set:
it moves `processed` to its tick only while `processed` is still what the tick read
when it began, and otherwise the whole batch is undone. The loser reads the store
again: if a tick as new or newer is in, it writes nothing; if not, it makes its
writes again from what it now reads (two tries at most, so a run sends 50 statements
or fewer, the free plan's queries for one run; a tick that loses twice writes nothing
and shows as a tick with no readings). So an older tick never overwrites a newer
tick's summary, and no summary is made from a store it did not read.

**History** (`shared/history.ts`). A sample adds one to its UTC day's count of
working, late or down readings for each part. A reading that is not working opens a
problem or extends the open one; a working reading closes it; more than 15 minutes
with no known reading closes it where the readings stopped, and the page says so.
Each tick also adds to the runs of checks with no answer: every tick between the last
one taken and this one, and each part this one could not check. A tick goes on from
the runs in the summary it read (written at the same `processed`, so no statement is
added); a store whose summary has none makes them once from its samples, one more read
on that tick only. Samples, days, closed problems and runs are kept 90 days. The page (`page/src/view.ts`)
names each bar from those counts and its own clock: "working all day" only for a
day checked from its first tick to its last, and the time not checked counted from
the day's start on the day the checks began. A past day is always counted to its
end. The clock's own day is counted to the summary's last check, and to the clock
once the summary is stale. So a page that could not refresh errs toward "not
checked", never toward "working": just after midnight UTC it can say yesterday
was "not checked for 5 minutes" although the checker did run, until its next
refresh.

**The page** (`status/page/`). `GET /api/status` answers the summary the last tick
wrote, with the server's clock, never from a cache (`no-store`, and the page asks
with `cache: 'no-store'`): an answer kept in the browser would carry an old clock,
and a reload would set the page's clock back. The page draws it, counts time from
the server's clock (never the visitor's), asks again shortly after each tick is
due, and says it has no recent checks once the summary is over 15 minutes old. It
then says only when the last check was, and every part's row reads "Could not
check": nothing old is shown as what is true now. It
draws again at once when its tab comes back to the screen, before the fetch that
follows settles. With scripts off it shows only the line that says to turn them on.
If its script has not started 10 seconds after the page opened (it did not load, or
scripts are off in a browser too old to know the rule that hides the boxes), the
stylesheet alone puts "This page did not finish loading." and "Reload it to try
again." where "Checking" was, and the parts stop saying "Checking"; the script's first act
is the mark on `<main>` that keeps that line away.
Every sentence it shows is in `page/src/copy.ts`.

**The deploy** (`status.yml`, job `deploy`, default branch only; one run at a time
on a branch, and a push on another branch never displaces one that waits) finds or
makes the
database, applies the migrations, deploys the checker, prints the store notice,
checks that the token can manage Pages, deploys the page, attaches
`status.snowlightmap.com` to the Pages project (and asks Cloudflare to look again
while the DNS record is not found), checks that the page answers at its `pages.dev`
address, and prints either the DNS record to add or that the name is live. The
record's value is read from Cloudflare, never assumed.

To work on it: `cd status && npm ci && npm run check && npm test && npm run build`.
`node scripts/preview.mjs` serves the built page on `127.0.0.1:4190` with made-up
histories (`test/fixtures/made-up.ts`: for tests and pictures only), and
`NODE_PATH=../web/node_modules node scripts/shots.cjs` takes pictures of each
state and checks that nothing moves when the page fills in, that scripts off shows
no "Checking" box, that a page whose script never loads says so after 10 seconds,
that coming back to the tab says an old answer's age at once, that the banner's
kept room holds every one of its headlines with its longest second line at every
2 px from 160 to 1040 px (so it does not grow when it fills), that the footer is not
drawn while the page waits, and that in every state, at nine widths from 320
to 1280 px and at text of 100%, 150% and 200%: the headline is never smaller than
the body text or its usual size and always larger than the line under it; nothing
scrolls sideways or reaches past its box; the axis labels keep half a line apart
or "Today" goes down a line under the last bar; no line breaks inside a name, a
date, a time, a length or a count; and no text ends in a line of one word where
wrapping could avoid it. The headline never shrinks to fit: a part's name that
does not fit at the end of a line moves to the next whole, and breaks between its
words only when it is wider than a whole line.

The page sends `X-Robots-Tag: noindex` on every address (`page/public/_headers`)
until the owner says the page may be listed. The commit that takes it off `/*`
puts it on `https://:project.pages.dev/*`, so only the real name is listed.
