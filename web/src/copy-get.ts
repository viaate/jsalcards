/**
 * The getsnowlight landing's words (get/index.html, served at https://www.getsnowlight.com,
 * where the map sends iPhone visitors): what Snowlight is, its iPhone app to come, the live map
 * today, privacy and questions. Kept out of src/copy.ts, so the map's first script carries none
 * of it. The same rules hold here as there, and `npm run lint:copy` reads this file as the
 * site's copy (scripts/check-copy.mjs COPY_MODULES). The page fills these in with
 * %copy.get.…% placeholders: tools/html-copy.ts pageCopy() puts the tree under `get` beside
 * copy.ts's own.
 *
 * The app's features are the app's to come; the page says plainly that the iPhone app is
 * coming this winter until the App Store link is set (tools/get-page.ts).
 */

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

export const getCopy = /* @__PURE__ */ deepFreeze({
  meta: {
    title: 'Snowlight for iPhone',
    description:
      'Every school closing in the US on one live map, and the chance your school calls it off tomorrow.',
  },
  /** The page's links to the live map (?map=1, remembered there, so this device is not sent here again). */
  openMap: 'Open the live map',
  /** Where the App Store badge goes once the app is out (tools/get-page.ts). */
  soon: 'The iPhone app is coming this winter',
  /** The App Store badge's label (Apple's artwork, shown only with VITE_APP_STORE_URL set). */
  badge: 'Download on the App Store',
  icon: 'Snowlight app icon',
  hero: {
    /** The page writes its last three words on a highlight (tools/get-page.ts markLast). */
    title: 'Know about snow days the night before.',
    lead: 'Snowlight puts every school closing, delay and early dismissal in the country on one live map, and tells you the chance your school calls it off tomorrow.',
    how: 'See how it works',
    facts: 'Free for iPhone · No ads · We never collect your location',
    phone:
      'Snowlight on iPhone with a middle school closed today, the weather and tomorrow’s chance',
  },
  open: {
    title: 'Your school, the second you open it.',
    body: 'Pick your school once. Snowlight opens straight to it: closed, late, remote or open, said in plain English, with the weather outside and tomorrow’s chance right underneath.',
    alert:
      'An alert from a middle school: 2-hour delay today. Buses run snow routes. No breakfast.',
  },
  chance: {
    title: 'One number for tomorrow.',
    body: 'Every evening Snowlight works out the chance your school closes tomorrow from the forecast for your school’s own town, when the snow and ice arrive, and how your district has called it before. You see the number and the reasons.',
    phone: 'The night before: a 64% chance of no school Wednesday, with the reasons',
  },
  map: {
    title: 'Every closing in the country, on one map.',
    body: 'Each school glows where it is, the moment its closing posts. From 3:30 PM on your school’s clock, the map turns to tomorrow and says so.',
    schools: '118,211',
    schoolsLabel: 'Schools on the map',
    lists: '400+',
    listsLabel: 'Closing lists watched',
    checks: '5 min',
    checksLabel: 'Between checks, mornings and evenings',
    phone: 'The live map with closed schools marked in blue',
  },
  unlock: {
    title: 'Know before you unlock.',
    body: 'An alert with your school’s own logo the moment it closes, widgets on your Lock Screen, and on a storm morning a Live Activity that follows the chance until your school makes the call.',
    lockScreen: 'Lock Screen with a closing alert and Snowlight widgets',
    liveActivity: 'A storm morning Live Activity following the chance of no school',
  },
  check: {
    title: 'Made for the 5 AM check.',
    body: 'Clear answers, big type and nothing to sign up for, so you can look, know, and go back to sleep.',
    plain: 'Plain English',
    plainBody:
      'Not codes. The same plain words in the app and in your alerts: “2-hour delay. Buses run snow routes. No breakfast.”',
    alerts: 'Alerts that know your school',
    alertsBody:
      'Save up to five schools. Hear when one closes, runs late or goes remote, when tomorrow’s chance gets high, and an evening check if you want it.',
    year: 'This school year',
    yearBody:
      'Every school keeps a count of its closed, late and remote days, so you know how many snow days are already used up.',
    share: 'Share the news',
    shareBody:
      'Send a clean card to your story or the group chat in one tap, with the day and the time it was posted.',
    private: 'Private by design',
    privateBody:
      'Snowlight never collects or stores your location, and a ZIP code works just as well. No ads, no tracking.',
  },
  game: {
    title: 'Call it before your school does.',
    body: 'A nightly game for snow-day believers. Pick closed or open, keep your streak and beat your friends. The odds come from the forecast, not other players, and flakes are just for fun.',
    phone: 'The nightly game on iPhone',
  },
  get: {
    title: 'Get Snowlight.',
    /** With the App Store link set. */
    app: 'Free on iPhone. Tomorrow’s call on your Lock Screen before the morning news.',
    /** Until then. */
    web: 'The live map works on your iPhone today, free and with no ads.',
    home: 'Add to Home Screen',
    homeSteps: {
      /** A link to the live map (?map=1), so the map the steps add is the map, not this page. */
      open: 'Open the live map in Safari',
      share: 'Tap Share, then Add to Home Screen',
      done: 'Open Snowlight from your home screen',
    },
  },
  faq: {
    title: 'Questions',
    free: 'Is Snowlight free?',
    freeAnswer: 'Yes. The map, the chance, alerts and the game are free, with no ads.',
    where: 'Where do the closings come from?',
    whereAnswer:
      'From local closing lists, checked every few minutes on school mornings and evenings. Your school’s own announcement is always the final word.',
    how: 'How is the chance worked out?',
    howAnswer:
      'From the forecast for your school’s town: how much snow and ice, when it falls, how cold the morning is, and how your district has decided before.',
    covered: 'Is my school covered?',
    coveredAnswer:
      'All 118,211 public and private schools in the US are on the map. A closing shows as soon as a list we read posts it.',
    location: 'Do you track my location?',
    locationAnswer:
      'No. We never collect your location. If you let Snowlight use it, your iPhone uses it to find schools near you, and we never receive or store it.',
  },
  footer: {
    tagline: 'Snow days, the night before.',
    features: 'Features',
    map: 'Live map',
    questions: 'Questions',
    rights: 'Copyright 2026 Snowlight',
  },
});
