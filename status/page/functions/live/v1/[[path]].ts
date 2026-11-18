/**
 * GET or HEAD /live/v1/<path>: a live file, read through this site for a page on a network
 * that blocks the live host (shared/live-proxy.ts). Every method is answered here.
 */

import { serveLive } from '../../../../shared/live-proxy.ts';

export const onRequest: PagesFunction = ({ request }) => serveLive(request);
