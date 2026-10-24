import type { PolicyScope } from '../api/programs';
import { boundedText, fullMatch, object, string, year } from './searchGuard';

export const match = (pattern: RegExp, v: unknown): v is string =>
  string(v) && fullMatch(pattern, v);
export const oneOf = (v: unknown, values: readonly string[]): v is string =>
  string(v) && values.includes(v);
export const hash = (v: unknown): v is string => match(/[a-f0-9]{64}/, v);
export const planId = (v: unknown) => match(/[a-z0-9][a-z0-9-]{0,99}/, v);
export const nonblank = (v: unknown, max: number): v is string =>
  boundedText(v, 1, max) && v.trim() !== '';
export const nullable = (v: unknown, check: (v: unknown) => boolean) =>
  v == null || check(v);
export function realDate(v: unknown): v is string {
  if (!match(/\d{4}-\d{2}-\d{2}/, v)) return false;
  const [y, m, d] = v.split('-').map(Number) as [number, number, number];
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return y >= 1 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1]!;
}
export function officialUrl(v: unknown, catalogYear: string) {
  if (!string(v)) return null;
  const pattern =
    /https:\/\/catalog\.northeastern\.edu\/(?:archive\/(\d{4}-\d{4})\/)?graduate\/([a-z0-9/-]+\/)/;
  const result = pattern.exec(v);
  return result?.[0] === v && (!result[1] || result[1] === catalogYear)
    ? result[2]!
    : null;
}
export function scope(v: unknown): v is PolicyScope {
  return (
    object(v) &&
    nonblank(v.program_id, 64) &&
    match(/[a-z][a-z0-9-]{0,39}/, v.campus) &&
    year(v.catalog_year) &&
    oneOf(v.pathway, ['standard', 'align', 'bridge']) &&
    nullable(v.concentration, (c) => nonblank(c, 100))
  );
}
export function scopeKey(v: PolicyScope) {
  return JSON.stringify([
    v.program_id,
    v.campus,
    v.catalog_year,
    v.pathway,
    v.concentration ?? '',
  ]);
}
