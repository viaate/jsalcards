/**
 * The waitlist page's script: tools/waitlist.ts bundles this file into a
 * classic script inline at the end of index.html, in a build with the
 * waitlist on. It runs once, after the page's markup is in.
 */
import { pageEnv, startWaitlist } from './gate.ts';

startWaitlist(pageEnv(window));
