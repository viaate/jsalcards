/**
 * The notifications' part of the service worker (src/pwa/push.ts): bundled by
 * tools/push-worker.ts into PUSH_FILE, which the generated worker imports.
 */

import { NOTIFY_ICON } from './config';
import { installPush, type PushScope } from './push';

declare const self: PushScope;

installPush(self, new URL(NOTIFY_ICON, self.registration.scope).href);
