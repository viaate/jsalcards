/**
 * Builders for the data tests: small directories and closings files in the
 * published formats, made up for these tests and used nowhere else.
 */
import type { ClosingsDay, ClosingsFile, SchoolDirectoryMeta } from '../../types/generated';

export interface TestSchool {
  readonly id: string;
  readonly name: string;
  readonly lon: number;
  readonly lat: number;
  /** Position in the districts list, or -1. */
  readonly district: number;
}

export const GENERATED_ON = '2026-01-05';

export function testMeta(
  schools: readonly TestSchool[],
  districts: readonly string[] = [],
): SchoolDirectoryMeta {
  return {
    schema_version: 1,
    generated_on: GENERATED_ON,
    count: schools.length,
    ids: schools.map((school) => school.id),
    names: schools.map((school) => school.name),
    districts: { ids: districts, names: districts.map((id) => `District ${id}`) },
    school_years: { public: '2024-2025', private: '2023-2024' },
  };
}

/** points.bin bytes for `schools`, as pipeline/snowlight/directory/points.py writes them. */
export function testPoints(schools: readonly TestSchool[], districtCount: number): ArrayBuffer {
  const bytes = new ArrayBuffer(16 + 13 * schools.length);
  const view = new DataView(bytes);
  for (let i = 0; i < 4; i++) view.setUint8(i, 'SLPT'.charCodeAt(i));
  view.setUint16(4, 1, true);
  view.setUint16(6, 13, true);
  view.setUint32(8, schools.length, true);
  view.setUint32(12, districtCount, true);
  schools.forEach((school, i) => {
    const at = 16 + 13 * i;
    view.setInt32(at, Math.round(school.lon * 1e6), true);
    view.setInt32(at + 4, Math.round(school.lat * 1e6), true);
    view.setUint32(at + 8, school.district < 0 ? 0xffffffff : school.district, true);
    view.setUint8(at + 12, 0);
  });
  return bytes;
}

/** A day group from rows of [school position, status], in school order. */
export function testDay(
  day: string,
  rows: readonly (readonly [number, 0 | 1 | 2 | 3])[],
): ClosingsDay {
  let previous = -1;
  const gaps = rows.map(([school]) => {
    const gap = school - previous - 1;
    previous = school;
    return gap;
  });
  const statuses = rows.map(([, status]) => status);
  const shifted = statuses.filter((status) => status === 1 || status === 3).length;
  return {
    day,
    gaps,
    statuses,
    announced: rows.map(() => null),
    reasons: rows.map(() => 0 as const),
    shifts: Array.from({ length: shifted }, () => null),
    clocks: Array.from({ length: shifted }, () => null),
  };
}

export function testClosings(
  generatedAt: string,
  meta: SchoolDirectoryMeta,
  days: readonly ClosingsDay[],
): ClosingsFile {
  return {
    schema_version: 1,
    generated_at: generatedAt,
    directory: {
      generated_on: meta.generated_on,
      schools: meta.count,
      districts: meta.districts.ids.length,
    },
    days,
  };
}

/** A Response the way fetch gives one. */
export function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
