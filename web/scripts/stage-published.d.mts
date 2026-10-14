/** The types of scripts/stage-published.mjs, for the tests that import it. */

export interface Stamp {
  readonly generated_on: string;
  readonly schools: number;
  readonly districts: number;
}

export interface StageOthers {
  readonly site: string;
  readonly to: string;
  readonly skip: (path: string) => boolean;
  readonly stamp: Stamp;
  readonly hashed: (path: string) => boolean;
  readonly putHashed: (path: string, bytes: Buffer) => void;
  readonly fail: (message: string) => never;
}

export function filesUnder(root: string, prefix?: string): string[];
export function published(path: string): boolean;
export function replayStampProblem(path: string, bytes: Buffer, stamp: Stamp): string | null;
export function checkStamps(
  options: Pick<StageOthers, 'site' | 'skip' | 'stamp' | 'hashed' | 'fail'>,
): void;
export function stageOthers(options: StageOthers): [string, number][];
