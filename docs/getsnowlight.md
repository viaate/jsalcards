# getsnowlight.com

The landing page for Snowlight on iPhone, and the redirect that sends iPhone
visitors of the map there.

## Where it lives

- **Source:** `web/get/` (the page, its pictures and fonts), with its words in
  `web/src/copy-get.ts` under the same copy rules as the map (`npm run lint:copy`).
- **Phone pictures:** one list, `web/get/phones.json`. To show another set,
  change each slot's `from` and run
  `node scripts/build-get-phones.mjs <design folder>` in `web/`; the page reads
  the file names from the same list.
- **Build:** `npm run build:get` in `web/` (`vite.get.config.ts`) writes the page
  to `web/dist-get/`. The map's build (`npm run build`, `web/dist/`) never
  carries it, and the map's first script and perf gates do not change.
- **Hosting:** the free Cloudflare Pages project `getsnowlight`, on the account
  the status page uses. `.github/workflows/getsnowlight.yml` builds and deploys
  it when its files change on the default branch, with the same
  `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets as the status page,
  makes the project on its first run, and attaches `www.getsnowlight.com`. It
  prints where the page answers (`getsnowlight.pages.dev`).
- **Lock:** until go-live the page carries the map's lock, as the map does. The
  workflow refuses to deploy a build without it.
- **App Store badge:** hidden until the repository variable `APP_STORE_URL`
  names the app's App Store page; then Apple's badge links there in place of
  "Open the live map" and "The iPhone app is coming this winter".

## The redirect

The map's build writes a small script at the top of `web/index.html`'s head, in
place of its `<!-- get-redirect -->` marker (`web/tools/get-redirect.ts`, where
the readable script and its explanation live; the page carries it minified, so
the map's page stays within its size budget). With the switch on, an iPhone in
Safari that opens the map's front page is sent to
`https://www.getsnowlight.com/`, on every visit until it chooses the map. Never:

- on a link to a school, a shared card or anything else with a query or a hash,
  or from any page but the front page under the build's base path;
- from the home screen;
- for a crawler, another browser or an app's own browser on iPhone, an iPod, an
  iPad, an Android phone or a desktop;
- before the site's lock is passed;
- where the browser cannot remember the choice.

When it sends, it stops the map's page first, so nothing more of the map loads
or shows.

The landing's "Open the live map", and the first of its Add to Home Screen
steps, open `https://snowlightmap.com/?map=1`. The map remembers that choice on
the device, takes `?map=1` out of the address bar, and never sends that device
again; the page the visitor then adds to the Home Screen is the map.

The one test of who is sent is `WHO` in `web/tools/get-redirect.ts`: the whole
user agent of Safari on iPhone. Widen it there to send other phones too.

**The switch** is `GET_REDIRECT` in `web/tools/get-redirect.ts`: `'on'` sends,
`'off'` sends no one. It lands off. A build can override it with
`VITE_GET_REDIRECT=on` or `off`; every e2e build of the map says `off`
(`web/playwright.config.ts`), and the redirect's own e2e tests switch it on in
the page they serve, so turning it on changes no test.

To go live, after the two GoDaddy steps below are in and
`https://www.getsnowlight.com` shows the page (otherwise iPhones would be sent
to an address that does not answer yet):

1. Change `export const GET_REDIRECT: Switch = 'off';` to `'on'` in
   `web/tools/get-redirect.ts`. That is the whole change.
2. After the deploy, the built page says `data-get-redirect="on"`.

**Turning it off again** is the same line back to `'off'`. The map's service
worker keeps a copy of the page, so an iPhone that has the map open or stored
keeps the old page, and with it the old switch, until its service worker
updates (on its next visit after the deploy, or the one after). A visitor sent
to the landing in that time can always come back with "Open the live map".

## The owner's two GoDaddy steps

In GoDaddy, for the domain getsnowlight.com:

1. **DNS:** set the record named `www` to type CNAME, pointing to
   `getsnowlight.pages.dev` (replace GoDaddy's default `www` record).
2. **Forwarding:** forward `getsnowlight.com` to `https://www.getsnowlight.com`,
   permanent (301), without masking. This replaces today's forward to
   snowlightmap.com.

The next run of the workflow sees the name and says when
`https://www.getsnowlight.com` is live.
