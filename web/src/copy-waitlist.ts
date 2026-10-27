/**
 * The waitlist page's words (index.html's waitlist blocks, privacy.html): the
 * part of the site's copy that only a waitlist build shows, kept out of
 * src/copy.ts so a build without the waitlist ships the same bytes as before.
 * The same rules hold here as there, and `npm run lint:copy` reads this file
 * as the site's copy (scripts/check-copy.mjs COPY_MODULES). Pages fill these
 * in with %copy.waitlist.…% placeholders: tools/html-copy.ts pageCopy() puts
 * the tree under `waitlist` beside copy.ts's own.
 *
 * Nothing here promises more than the site does: one email when Snowlight
 * goes live, and nothing collected but the email address.
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

const headline = 'Every school closing in the US, live on one map.';
const when = 'Coming this winter.';

export const waitlistCopy = /* @__PURE__ */ deepFreeze({
  /** The page's <title> and the share card read shareTitle; the search result reads description. */
  meta: {
    description: `${headline} ${when} Join the waitlist to hear when it goes live.`,
    shareTitle: 'Snowlight: every school closing, live on one map',
    shareImageAlt: 'Snowlight. Every school closing in the US, live on one map.',
  },

  headline,
  when,

  /**
   * Under `when`: where the chances come from, in the owner's words (Oct 26, 2026), and the
   * one string allowed to say "prediction model" (scripts/check-copy.mjs BANNED_EXCEPTIONS).
   * Each part is true of what docs/predict.md says ships:
   * - "every school in the lower 48": `snowlight predict` gives every public school district,
   *   and every private school of the contiguous states, a chance (docs/predict.md lines 3-4,
   *   and 319-326: "Alaska and Hawaii get none, as their districts get none"), so it says the
   *   lower 48, not the US.
   * - "a prediction model trained on real closings": the model as fit (docs/predict.md line 15
   *   on) is fit to labeled school days, each label read from a real closing list kept that
   *   morning (lines 17-20: 1,547 no-school district-days among them), and its walk-forward
   *   backtest trains each fold on those labels alone (lines 118-121).
   */
  model:
    'Snow day chances for every school in the lower 48, from a prediction model trained on real closings.',

  form: {
    /** The email field's label, read aloud and shown as its placeholder. */
    email: 'Email address',
    join: 'Join the waitlist',
    joining: 'Joining',
    /** Under the button: who it is for and what they get, when the list sends no confirmation email. */
    terms:
      'You must be 13 or older. One email when Snowlight goes live. Unsubscribe anytime. Never sold.',
    /** The same, when the list first asks each new address to confirm (Kit’s double opt-in). */
    termsConfirm:
      'You must be 13 or older. One email to confirm, one when Snowlight goes live. Unsubscribe anytime. Never sold.',
    privacy: 'Privacy',
  },

  /** After the list takes the address. */
  done: {
    /** The title when the list sends no confirmation email: the address is on the list. */
    title: 'You’re on the list.',
    /**
     * The title when the list first asks a new address to confirm (Kit’s double opt-in): a
     * new address is not on the list until it is confirmed, so the title says only what is
     * true of every signup.
     */
    titleConfirm: 'Thanks for signing up.',
    /**
     * Shown when the list sends a confirmation email first (Kit’s double opt-in).
     * Kit sends it only to a new address, so it is asked of a first signup alone.
     */
    confirm: 'First time joining? Confirm the email we just sent to finish.',
    /** Shown when it does not. */
    noConfirm: 'We’ll email you once, when Snowlight goes live.',
  },

  /** Kit holds the signup until the person passes its spam check, on its own page. */
  check: {
    title: 'One more step.',
    body: 'Confirm you’re a person to finish joining.',
    link: 'Finish joining',
  },

  errors: {
    invalid: 'Enter a full email address, like name@example.com.',
    rejected: 'That email address did not go through. Check it and try again.',
    /** The device says it has no connection, so nothing was sent. */
    offline: 'This device is offline. Connect to the internet and try again.',
    /**
     * Sent, but no answer the page could read came back (it took too long, the connection
     * dropped, or the answer was not what Kit sends): the page cannot know whether Kit has the
     * address, and a second signup of it does no harm.
     */
    unknown: 'We could not tell whether that went through. Try again. Joining twice does no harm.',
    server: 'The waitlist is not taking signups right now. Try again later.',
  },

  /** The quiet way in for people with the code. */
  code: {
    open: 'Have an access code?',
    field: 'Access code',
    wrong: 'That code is not right.',
  },

  /** privacy.html, in plain words. */
  privacy: {
    title: 'Privacy',
    back: 'Back to Snowlight',
    intro: 'The Snowlight waitlist keeps one thing about you: your email address.',
    sections: {
      what: {
        heading: 'What we collect',
        body: 'Only the email address you type in. No name, no location, nothing else.',
      },
      why: {
        heading: 'Why',
        body: 'To send you one email when Snowlight goes live. We never sell it or share it for anyone else’s use.',
        /** The same, when the list first asks each new address to confirm. */
        bodyConfirm:
          'To send you one email to confirm it, and one when Snowlight goes live. We never sell it or share it for anyone else’s use.',
      },
      who: {
        heading: 'Who handles it',
        body: 'Kit (kit.com), the email service that keeps the list and sends our emails. Like any website, it also sees the internet address your browser sends from.',
        link: 'Kit’s privacy policy',
      },
      age: {
        heading: 'Age',
        body: 'The waitlist is for people 13 or older. If someone younger signs up, we delete the address when we learn of it.',
      },
      remove: {
        heading: 'How to be removed',
        body: 'Every email has an unsubscribe link. To have your address deleted, reply to any of our emails and ask.',
        /**
         * The same, when the list first asks each new address to confirm: Kit’s confirmation
         * email may carry no unsubscribe link, so the line claims one only for the emails after it.
         */
        bodyConfirm:
          'Every email after the one that asks you to confirm has an unsubscribe link. To have your address deleted, reply to any of our emails and ask.',
        /** With a contact address (VITE_WAITLIST_CONTACT): a line, then a link that writes to it. */
        contact: 'To be removed at any time, or to tell us about a signup by someone under 13:',
        contactLink: 'Email us',
      },
    },
  },
});
