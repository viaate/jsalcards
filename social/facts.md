# Snowlight facts for posts on @SnowlightMap

The only things a post may state (docs/social.md). Public facts only: nothing private, no
names of people, schools, districts or stations, nothing about how the chances are worked
out. Each line is one fact: `- [STATUS] id: text | terms: words that name it in a post`,
optionally `| except: phrases`: phrases that hold a term but name another fact.

- LIVE: true and running now.
- TESTING: built, but only in practice mode or behind the lock; a post must say so.
- COMING: not built or not on yet; a post must say it is coming.

The lead keeps this file current: when something ships, move its fact to LIVE in the same
change that ships it.

## Facts

- [LIVE] founder: I am the founder building Snowlight, and I post what I build here.
- [LIVE] waitlist: The Snowlight waitlist is open, and the link is in my bio. Joining means one email when Snowlight goes live; the address is never sold. | terms: waitlist
- [LIVE] reader: The live closings reader runs 24/7 in practice mode. It checks school closing lists every 5 minutes from 4 to 9 AM and 6 to 11 PM local time and during winter weather alerts, and every 30 minutes otherwise. | terms: closings reader, reader, closing lists
- [TESTING] practice: In practice mode, what the reader finds is not shown on the map yet; I check its work before anything goes public. | terms: practice mode, practice
- [LIVE] directory: Snowlight's school directory holds 118,211 US K-12 schools in 18,227 districts, public and private. | terms: directory, school directory
- [TESTING] map: The map is in private testing behind a lock; only I can open it before launch. It is a near-black map of the US with every school on it. | terms: the map, map, the site, the app, website
- [TESTING] search: On the map you can search by school, city or ZIP code. | terms: search, zip code, zip codes
- [TESTING] chances: Every school day the map shows a chance of no school today and tomorrow for every public school district and every private school in the lower 48 states, refreshed about every 30 minutes. In late October that chance is 1% almost everywhere; it rises when the weather service puts out a winter storm warning or advisory for the area. | terms: chance, chances, snow day chances, odds, prediction, predictions, forecast, forecasts
- [COMING] glow: At launch, every school that is closed, delayed, remote or dismissing early for weather will glow on the map like city lights seen from space. | terms: glow, glows, glowing, lights up, light up, lit up, city lights
- [COMING] closings: Live school closings on the map, for every state, starting this winter. | terms: closings, closing, closed, closures, closure, closes, delays, delayed, school is closed, schools are closed, which schools | except: closings reader, closing lists
- [COMING] aim: Every school closing in the US on one map, coming this winter. | terms: every school closing, one map
- [TESTING] watches: A winter storm watch can raise a district's chance; I am testing that quietly in the background first, and the map does not show it yet. | terms: watch, watches, winter storm watch
- [COMING] notifications: Notifications on your phone when your school closes or its chance jumps. | terms: notification, notifications, notify, push alert, push alerts, alert, alerts, text, texts, phone | except: weather alert, weather alerts
- [COMING] launch: Snowlight goes live this winter; the plan is to launch before the first real snow. | terms: launch, launches, launching, launched, goes live, go live, going live
