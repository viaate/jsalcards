/**
 * The installable, offline app: what the page calls. The build side (the
 * VitePWA options) is in config.ts, which vite.config.ts reads.
 *
 *   window.addEventListener('load', () => void registerServiceWorker());
 *
 * (registerServiceWorker waits for load and an idle moment itself, so calling
 * it any time after startup is fine.)
 */

export { registerServiceWorker } from './register';
export type { RegisterHost, RegisterOptions, ServiceWorkerHandle } from './register';
export { dataRoot, evictStaticData, onDataUpdate, warmDataCache } from './data';
export type { DataCacheHost } from './data';
export { CACHE_NAMES, DATA_DIR, MANIFEST_FILE, SW_FILE } from './config';
