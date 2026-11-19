/**
 * The page "How Snowlight guesses" (WHY-PLAIN 3f; ui/LegalPage.svelte at ?how, opened from the
 * school panel's why and from the menu's About page): how a chance is made, in plain words, for
 * middle schoolers and parents. It loads with the page that shows it, never with the page's first
 * script. `npm run lint:copy` reads it as the site's copy (scripts/check-copy.mjs COPY_MODULES),
 * and copy-chance.test.ts holds each paragraph to grade 8 and 20 words a sentence.
 *
 * Numbers that move with the data (each kind of day's start, the typical district's days, the
 * late-start chance) are not written here: the school's panel shows each one that day, from the
 * files. Only the fixed rules are (config/predict.yaml and pipeline/snowlight/predict).
 */

import type { LegalDocument } from './copy-legal';

/** Recursively freezes an object graph so no string can be changed at runtime. */
function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

const section = (heading: string, paragraphs: readonly string[]) => ({
  heading,
  blocks: paragraphs.map((p) => ({ p })),
});

export const howCopy: LegalDocument = /* @__PURE__ */ deepFreeze({
  title: 'How Snowlight guesses',
  blocks: [
    { p: 'Snowlight gives each school a chance of no school for each day. Here is how we get it.' },
    { p: 'A 30% chance means about 3 in 10 days like this would have no school.' },
  ],
  sections: [
    section('Days with a storm alert', [
      'Each kind of alert day has its own start. Every district starts at the same chance for the same kind of day. The school’s page shows it.',
      'We set these starts from past school closing lists. Most of those lists were kept on storm mornings, so we fix for that.',
      'This winter’s storms can move these starts. If they do, the school’s page says so.',
    ]),
    section('How often storms come', [
      'Places that get lots of storm alerts start lower. Places that get few start higher. A place used to storms closes less for each one.',
      'We count alert days on school days, over the past winters.',
      'A typical district is one in the middle of the districts that get these alerts. Half of them get more, and half get fewer. The school’s page shows how many days it has in a winter.',
      'Some districts never get one kind of alert. We leave them out when we find the typical district.',
      'Some districts have only charter or online schools, so we have no alert counts of their own. For them, we use a typical district in their county. Private schools always use their county.',
      'In some parts of the country, districts close less on winter advisory days than in the rest. We start those places a bit lower. In others, they close more, and we start them a bit higher.',
    ]),
    section('Which alerts count', [
      'Storm warnings are winter storm, ice storm, blizzard and lake effect snow warnings. Where they happen, hurricane and tropical storm warnings count too.',
      'Winter advisories are winter weather, freezing rain and lake effect snow advisories. Cold warnings are extreme cold and wind chill warnings.',
      'An alert counts for a district when it covers at least half of its main schools. An alert for high places counts at schools up high, and at schools up to 500 feet below. It also counts where we do not know a school’s height.',
      'A district’s main schools are its schools that are not charter or online schools. A district of only charter or online schools uses all of them.',
    ]),
    section('The snow forecast', [
      'At 9 PM the evening before, we look at the forecast. Before that, the chance does not use it.',
      'We count the snow still to come by late morning. The school’s page shows the exact time. We use the amount that half of the main schools get or more.',
      'Each place has a usual amount of snow. With that much, snow does not change the chance. More snow raises it, and less lowers it.',
      'We set the usual amount from past forecasts on its days with that kind of alert. We add 10 days from its county or part of the country, when they have any. Where past days had ice, the usual snow alone can be lower. It is never under a third of the usual amount.',
      'Ice counts too. Each 0.1 inch of ice counts like 2.5 inches of snow. Cold counts a little. Each degree under 15 degrees at 7 AM adds a bit, down to 0 degrees.',
      'A forecast can lower an alert day only so far. Past a lot of snow, more adds less and less. A winter advisory day never goes above a storm warning day with the same forecast.',
      'The forecast does not change blizzard, cold, hurricane or tropical storm warning days. It does not change private schools either, since they have no district.',
    ]),
    section('Keeping days off normal', [
      'We do not let any district’s chances add up to more than 6 days off a winter. If they would, we lower them.',
      'We also keep the whole country’s days off in a normal range. If the forecast would push them too high, we leave it out that day.',
    ]),
    section('A late start', [
      'When school is on during a storm alert, some schools start late. For each kind of alert, we set how often that happens. The school’s page shows the chance of a late start.',
    ]),
    section('A district’s habit', [
      'We look at past closing lists to see what each district did on storm days. This winter’s days are not in them yet.',
      'For no school and late starts, we count only closings for the weather or with no reason given. A day counts as no school when at least half of its main schools were closed or remote. It counts as a late start when at least half of them started late. It counts as school when at most 1 in 10 of them were closed, remote, late or let out early. Here any reason counts. Other days are left out.',
      'To tell a district’s habit, we need at least 5 of its days with one kind of alert. Then we compare it with every other district on the same kind of day.',
      'Most past lists were kept on storm mornings, so they show mostly days off. That is why we compare a district with other districts, not with every day.',
      'A district tends to close easily if it closes more often than the other districts. It tends to hold out if it closes less often than they do. If it is close to them, it is about like most districts.',
      'We only say this when a gap that big would come from luck less than 1 time in 20.',
      'On storm days, the chance does not use a district’s habit yet. We are testing that now.',
    ]),
    section('Days with no storm alert', [
      'On days with no winter warning or advisory, the chance comes from past days like this.',
      'We use the district’s own past days when it has enough of them. If not, we use districts near it. Next come its county, its state, its part of the country and the whole country.',
    ]),
    section('What we do not count', [
      'We do not count the day of the week, wind or how high a school is. The only height that counts is for alerts for high places.',
      'When districts next door post a closing, that can raise the chance. The school’s page says so when it does.',
      'We do not count the hour by hour snow in the night chart. We count the forecast at 9 PM.',
    ]),
    section('When a school posts', [
      'When a school or district posts that it is closed, late or remote, we show that instead of a chance.',
    ]),
  ],
});
