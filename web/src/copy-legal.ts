/**
 * The privacy policy and the terms of use (ui/LegalPage.svelte, at ?privacy and ?terms): the
 * owner's approved text, word for word (the draft's rev 14 of Nov 9, 2026, filled in on the
 * owner's "just fill it in"). It loads with the page that shows it, never with the page's first
 * script. `npm run lint:copy` reads it as the site's copy (scripts/check-copy.mjs COPY_MODULES);
 * the few places the approved words step outside the house style are listed there, for this file
 * alone (LEGAL_MODULE). Change no word here without the owner.
 *
 * A page is its title and its blocks, and each section its heading and its blocks. A block is one
 * of three: `{ p }` a paragraph, `{ list }` a list whose items may start with a bold `lead`, or
 * `{ table }` a table, whose empty cells are null.
 */

/** One item of a list: its words, after a bold lead where it has one. */
export interface LegalItem {
  readonly lead?: string;
  readonly text: string;
}

/** A table: its heading row and its rows, cell by cell (null: an empty cell). */
export interface LegalTable {
  readonly head: readonly string[];
  readonly rows: readonly (readonly (string | null)[])[];
}

export type LegalBlock =
  { readonly p: string } | { readonly list: readonly LegalItem[] } | { readonly table: LegalTable };

export interface LegalSection {
  readonly heading: string;
  readonly blocks: readonly LegalBlock[];
}

export interface LegalDocument {
  readonly title: string;
  readonly blocks: readonly LegalBlock[];
  readonly sections: readonly LegalSection[];
}

/** The two pages, by the name the address gives them (?privacy, ?terms). */
export type LegalPageName = 'privacy' | 'terms';

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

const CONTACT = 'hello@snowlightmap.com';

const privacy: LegalDocument = {
  title: 'Privacy policy',
  blocks: [
    {
      p: 'You can use Snowlight’s map and snow-day chances without an account, and we collect nothing about you to do that. We collect personal information only when you make an account, turn on alerts or join the waitlist, and only what each of those needs.',
    },
  ],
  sections: [
    {
      heading: 'What we collect, and why',
      blocks: [
        {
          table: {
            head: ['When', 'What we keep', 'Why'],
            rows: [
              [
                'You use the map',
                'Nothing. There are no ads, no analytics and no tracking cookies.',
                null,
              ],
              [
                'You make an account',
                'Your name, email, username, a join number, up to 5 saved schools, when you signed up and last logged in, and scrambled keys made from your password (never the password itself)',
                'To log you in and keep your schools',
              ],
              [
                'You stay logged in',
                'A scrambled copy of a random login token, for 30 days after your last visit',
                'So you don’t log in every time',
              ],
              [
                'You turn on alerts',
                'Your browser’s push address, your alert settings (which kinds, your chance threshold, your evening check time, quiet hours) and a log of alerts sent',
                'To send the alerts you chose, and never the same one twice',
              ],
              [
                'You play Call it',
                'Your calls, your flakes and your streak, shown with your username',
                'To run the game and its leaderboards',
              ],
              [
                'You join the waitlist',
                'Your email address only',
                'To send you one email when Snowlight opens',
              ],
            ],
          },
        },
        { p: 'Your username and join number are public. Your name and email are not.' },
      ],
    },
    {
      heading: 'Your location',
      blocks: [
        {
          p: 'Snowlight asks for your location only when you tap to find schools near you, and only with your permission. Your phone or browser uses it to move the map; Snowlight never receives or stores it. You can type a school, city or ZIP code instead.',
        },
        {
          p: 'When you zoom in, the street map comes from OpenFreeMap, which sees which map area your device asks for, as any map service does.',
        },
      ],
    },
    {
      heading: 'What stays on your device',
      blocks: [
        {
          p: 'Your browser keeps a few things on your device so the site remembers them: the school you pinned, your theme, and your login token. Clearing your site data removes them.',
        },
      ],
    },
    {
      heading: 'Who handles your information',
      blocks: [
        {
          list: [
            { lead: 'Cloudflare', text: 'runs our accounts service and its database.' },
            { lead: 'GitHub', text: 'hosts the website and runs the jobs that send alerts.' },
            {
              lead: 'Apple, Google, Microsoft or Mozilla',
              text: ', through your browser’s or phone’s push service, deliver alerts to your device.',
            },
            { lead: 'Kit', text: '(kit.com) keeps the waitlist and sends its email.' },
            { lead: 'OpenFreeMap', text: 'serves the zoomed-in street map.' },
          ],
        },
        {
          p: 'Like any website, each of them sees the internet address your device connects from. We use that address only briefly, to stop repeated sign-in or sign-up attempts. We never sell your information or share it for anyone else’s advertising.',
        },
      ],
    },
    {
      heading: 'How long we keep it',
      blocks: [
        {
          p: 'We keep your account until you delete it. Deleting it, in Settings, removes your name, email, username, saved schools, keys, sessions, push addresses, alert settings and alert log at once. Two traces remain for a short time:',
        },
        {
          list: [
            {
              text: 'For 30 days a scrambled form of your old username stays reserved, linked to nothing, so nobody can take it and pretend to be you.',
            },
            {
              text: 'Our database provider keeps restore points for 7 days, after which those copies are gone too.',
            },
          ],
        },
        { p: 'Your join number is never given to anyone else.' },
      ],
    },
    {
      heading: 'Children',
      blocks: [
        {
          p: 'Accounts, alerts and the waitlist are for people 13 or older, and the sign-up form asks. If we learn that someone under 13 has given us personal information, we delete it.',
        },
      ],
    },
    {
      heading: 'Your choices',
      blocks: [
        {
          list: [
            {
              text: 'Turn alerts off at any time in Settings, or in your phone’s or browser’s settings.',
            },
            { text: 'Change your account details in Settings.' },
            { text: 'Delete your account in Settings, or ask us to.' },
            { text: 'Leave the waitlist with the unsubscribe link in any of its emails.' },
          ],
        },
      ],
    },
    {
      heading: 'Changes',
      blocks: [
        {
          p: 'If we change this policy in a way that matters, we will say so on the site before the change takes effect.',
        },
      ],
    },
    {
      heading: 'Contact',
      blocks: [{ p: `Questions or requests: ${CONTACT}.` }],
    },
  ],
};

const terms: LegalDocument = {
  title: 'Terms of use',
  blocks: [
    {
      p: 'Snowlight shows school closings and estimates the chance of a snow day. It is not your school’s announcement, and your school’s own word always wins. By using Snowlight you agree to these terms.',
    },
  ],
  sections: [
    {
      heading: 'What Snowlight is, and is not',
      blocks: [
        {
          list: [
            {
              lead: 'Closings come from public lists.',
              text: 'We read local closing lists every 5 minutes on school mornings and evenings, less often at other times, and match them to schools. A list can be wrong, late or read wrong, so a closing can show late, show wrong, or be missed.',
            },
            {
              lead: 'The chance is an estimate.',
              text: 'It comes from the forecast and from how districts have decided before. It is never a promise that school will or won’t open.',
            },
            {
              lead: 'Alerts can be late or missed.',
              text: 'They depend on your phone, your browser, your connection and push services we don’t run.',
            },
            {
              lead: 'Not for emergencies or safety decisions.',
              text: 'Check your school or district before you act, especially on travel, child care or work.',
            },
          ],
        },
      ],
    },
    {
      heading: 'Your account',
      blocks: [
        {
          list: [
            { text: 'You must be 13 or older to make an account.' },
            {
              text: 'Keep your password to yourself. You are responsible for what happens under your account.',
            },
            {
              text: 'Usernames are public. We may change or remove a username that is offensive, impersonates someone, or breaks these terms.',
            },
            { text: 'We may suspend or close an account that breaks these terms.' },
          ],
        },
      ],
    },
    {
      heading: 'Call it and flakes',
      blocks: [
        {
          list: [
            {
              text: 'Flakes are points for fun. They have no cash value and can’t be bought, sold, traded or exchanged for money, prizes or anything else.',
            },
            {
              text: 'The odds in Call it come from the forecast, not from other players. Calls never change a school’s chance or status.',
            },
            {
              text: 'We may reset, adjust or remove flakes, calls or streaks to fix mistakes or stop cheating.',
            },
          ],
        },
      ],
    },
    {
      heading: 'Acceptable use',
      blocks: [
        { p: 'Don’t:' },
        {
          list: [
            { text: 'break the law or other people’s rights using Snowlight;' },
            { text: 'try to get into accounts or systems that aren’t yours;' },
            {
              text: 'overload, attack or disrupt the site or its services, including with automated sign-ups or calls;',
            },
            { text: 'pretend to be a school, a district or another person.' },
          ],
        },
      ],
    },
    {
      heading: 'School names and logos',
      blocks: [
        {
          p: `School and district names and logos belong to their owners. We show them only to identify each school. A school or district that wants its logo removed can ask us at ${CONTACT}.`,
        },
      ],
    },
    {
      heading: 'Availability and changes',
      blocks: [
        {
          p: 'We may change, pause or end any part of Snowlight at any time. We will try to keep it running on storm mornings, but we can’t promise it will always be available or error-free.',
        },
      ],
    },
    {
      heading: 'Disclaimers and limits',
      blocks: [
        {
          p: 'Snowlight is provided as is, without warranties of any kind. To the extent the law allows, we are not liable for any loss from using it or relying on it, including a missed, late or wrong closing, chance or alert.',
        },
      ],
    },
    {
      heading: 'Changes to these terms',
      blocks: [
        {
          p: 'If we change these terms in a way that matters, we will say so on the site before the change takes effect. Using Snowlight after that means you accept the new terms.',
        },
      ],
    },
    {
      heading: 'Law and contact',
      blocks: [
        {
          p: `These terms are governed by the laws of the United States. Questions: ${CONTACT}.`,
        },
      ],
    },
  ],
};

export const legalCopy = /* @__PURE__ */ deepFreeze({
  pages: { privacy, terms } satisfies Record<LegalPageName, LegalDocument>,
});
