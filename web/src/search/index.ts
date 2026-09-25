/**
 * Snowlight search: typo-tolerant, grouped search over schools, districts,
 * cities and ZIP codes, run in a worker.
 *
 * Import this lazily (after first paint): it pulls in only the small client;
 * the engine ships in the worker's own chunk.
 */
export {
  DEFAULT_QUERY_TIMEOUT_MS,
  SearchUnavailableError,
  createSearchClient,
  isAbortError,
} from './client';
export type { ClientOptions, SearchClient, SearchOptions, WorkerLike } from './client';
export type {
  GroupName,
  IndexInfo,
  MatchKind,
  RecordKind,
  SearchHit,
  SearchRecord,
  SearchResults,
} from './types';
