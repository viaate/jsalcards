/**
 * Snowlight's status checker. It has no URL: Cloudflare's cron starts it every 5 minutes, it
 * looks at the four parts and writes what it found to the store the status page reads.
 */

import { tick } from './tick.ts';
import type { Env } from './tick.ts';

export default {
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const t = Math.floor(controller.scheduledTime / 300000) * 300;
    await tick(env, t, {
      fetch: (url, init) => fetch(url, init),
      now: () => Date.now(),
      wait: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    });
  },
} satisfies ExportedHandler<Env>;
