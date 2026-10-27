# Snowlight facts for posts on @SnowlightMap

HAIKU_POSTS = off

The line above switches the daily post Claude Haiku writes (docs/social.md, "The Haiku
writer's switch"). While it says `off`, only the queued posts the lead wrote and checked go
out, and no run calls Anthropic, even with ANTHROPIC_API_KEY set. The lead sets it to `on`
once the checks on Haiku's drafts have passed one more review round.

The only things a post may state (docs/social.md). Public facts only: nothing private, no
names of people, schools, districts or stations. Each line is one fact:
`- [STATUS] id: text | terms: words that name it in a post`, optionally
`| except: phrases`: phrases that hold a term but name another fact.

- LIVE: true and running now.
- TESTING: built, but behind the lock or switched off; a post must say so.
- COMING: not built or not on yet; a post must say it is coming.

The lead keeps this file current: when something ships, move its fact to LIVE in the same
change that ships it.

The `chances` fact is the switch for chance numbers (docs/social.md, "Chances while the site is
locked"): while it is TESTING, no post, card, alt text or picture description gives any
chance, and the picture is never a district's chance. When the owner unlocks the site, mark it
LIVE (and give its numbers here, if any) and chance cards come back with no code change.

## The prediction model

Model first (docs/social.md): every post states one LIVE fact below whose id starts with
`model`, in plain words, so people know Snowlight's chances come from a real prediction model
trained on real closing records. Every number here is from docs/predict.md and the committed
model file (`pipeline/data/predict/model.json.gz`). No accuracy number is ever posted: the
past records lean toward big storm days, so a score on them would not be a fair one.

- [LIVE] model: Snowlight's chances come from a prediction model trained on real closing records, not a guess: a real model, not a guess, built on real past school days, where what happened that day is on record. | terms: prediction model, real prediction model, statistical model, model, not a guess, aren't a guess, isn't a guess, built on real closing records, real closing records
- [LIVE] model-days: The district model is trained on 2,388 real past school days with a known outcome, each one district on one day, from the records of 11 past winters: 1,547 with no school, 109 with a delayed start and 732 open. | terms: trained on, known outcome, known outcomes, past school days
- [LIVE] model-private: Private schools get their own chance from the same kind of model, trained on 661 real past private school days with a known outcome. | terms: private school days, their own chance
- [LIVE] model-places: For each kind of weather day, the model uses a district's own recorded days where it has enough of them, and leans on the records of its nearby districts, county, state, region and the whole country where it has fewer. | terms: own record, own recorded days, recorded days, nearby districts, whole country
- [LIVE] model-alerts: The model sorts each school day by the National Weather Service winter alerts over the district, such as a winter weather advisory, a winter storm warning, an ice storm warning or a blizzard warning, or none, and the chance moves when those alerts change. | terms: weather service, winter alert, winter alerts, winter storm warning, advisory, blizzard warning, ice storm warning
- [LIVE] model-tested: I tested the model walk-forward on past winters: each winter was scored by a model fit only to the winters before it, so it never saw the days it was scored on. | terms: walk-forward, past winters, never saw
- [LIVE] model-refresh: The model works out a new set of chances about every 30 minutes, and sooner when the weather service changes its winter alerts. | terms: every 30 minutes, new set of chances
- [TESTING] model-reasons: Reasons from the weather forecast, like how much snow or ice is on the way, are built into the model but switched off while I test them; no chance uses the forecast yet. | terms: forecast, forecasts, forecasted, how much snow, inches, reasons
- [TESTING] model-outlook: A night-before outlook, which would weigh the evening's alerts and forecasts for the next morning, is built and was scored on past winters; I am testing it quietly in the background, so no chance anyone sees uses it yet. | terms: night-before, night before, outlook, outlooks
- [TESTING] watches: A winter storm watch can raise a district's chance; I am testing that quietly in the background first, and the map does not show it yet. | terms: watch, watches, winter storm watch
- [COMING] model-learning: Once closings are on the map this winter, the model will learn from each finished school day's real closings, and a refit takes over only when held-out days show it is no worse. | terms: learn from, learns, learning, relearn, relearns, retrain, retrains, retrained, refit, refits

## Facts

- [LIVE] founder: I am the founder building Snowlight, and I post what I build here.
- [LIVE] waitlist: The Snowlight waitlist is open, and the link is in my bio. Joining means one email when Snowlight goes live; the address is never sold. | terms: waitlist
- [LIVE] reader: The live closings reader runs 24/7, checking school closing lists every 5 minutes from 4 to 9 AM and 6 to 11 PM local time and during winter weather alerts, and every 30 minutes otherwise. | terms: closings reader, reader, closing lists
- [LIVE] directory: Snowlight's school directory holds 118,211 US K-12 schools in 18,227 districts, public and private. | terms: directory, school directory
- [TESTING] map: The map is in private testing behind a lock; only I can open it before launch. It is a near-black map of the US with every school on it. | terms: the map, map, the site, the app, website
- [TESTING] search: On the map you can search by school, city or ZIP code. | terms: search, zip code, zip codes
- [TESTING] chances: Every school day the model works out a chance of no school and a chance of a delayed start, today and tomorrow, for every public school district and every private school in the lower 48 states. While I test them they show only on the locked map, so no post or picture gives a chance number. | terms: chance, chances, snow day chances, odds, prediction, predictions, delayed start
- [LIVE] closings: Real school closings and delays go into Snowlight within minutes of the reader finding them, and they stay private until launch. | terms: closings, closing, closed, closures, closure, closes, delays, delayed, school is closed, schools are closed, which schools | except: closings reader, closing lists, closing records, delayed start, delayed starts
- [LIVE] glow: Every school that is closed, delayed, remote or dismissing early for weather glows like city lights seen from space. | terms: glow, glows, glowing, lights up, light up, lit up, city lights
- [COMING] aim: Every school closing in the US on one map, coming this winter. | terms: every school closing, one map
- [COMING] notifications: Notifications on your phone when your school closes or its chance jumps. | terms: notification, notifications, notify, push alert, push alerts, phone alert, phone alerts, text alert, text alerts, alert you, alerts you, alerted, text, texts, phone
- [COMING] launch: Snowlight goes live this winter; the plan is to launch before the first real snow. | terms: launch, launches, launching, launched, goes live, go live, going live
