/**
 * The words of the two small links to the privacy policy and the terms of use
 * (ui/LegalLinks.svelte, to ?privacy and ?terms, app/legal.ts), at the foot of
 * Settings and of the menu's About page. The part of src/copy.ts that loads
 * with those links rather than with the page, kept apart from the pages' own
 * words (src/copy-legal.ts) and from the account controls' (src/copy-account.ts)
 * so showing two links fetches neither. The same rules hold here as there, and
 * `npm run lint:copy` reads this file as the site's copy (scripts/check-copy.mjs
 * COPY_MODULES).
 *
 * Each link is named by its page's own title (copy-legal.ts legalCopy.pages),
 * so neither reads as the Privacy row in Settings; ui/tests/legal-links.test.ts
 * holds them equal.
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

export const legalLinksCopy = /* @__PURE__ */ deepFreeze({
  privacy: 'Privacy policy',
  terms: 'Terms of use',
  /** The page "How Snowlight guesses" (copy-how.ts), from About and from a school's why. */
  how: 'How Snowlight guesses',
});
