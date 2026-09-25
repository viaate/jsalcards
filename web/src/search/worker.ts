/**
 * Search worker entry: loads the index and answers queries off the main
 * thread. Created by client.ts; see server.ts for the protocol.
 */
import { serve } from './server';

serve(globalThis);
