export const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);
export const string = (v: unknown): v is string => typeof v === 'string';
export const fullMatch = (pattern: RegExp, text: string) =>
  pattern.exec(text)?.[0] === text;
export const integer = (v: unknown, min = 0, max = Infinity): v is number =>
  typeof v === 'number' &&
  Number.isFinite(v) &&
  Number.isInteger(v) &&
  v >= min &&
  v <= max;
export const boundedText = (
  v: unknown,
  min: number,
  max: number,
): v is string =>
  string(v) && Array.from(v).length >= min && Array.from(v).length <= max;
export function list<T>(
  v: unknown,
  guard: (item: unknown) => item is T,
): T[] | null {
  return Array.isArray(v) && Array.from(v).every(guard)
    ? ([...v] as T[])
    : null;
}
export const strings = (v: unknown) => list(v, string);
export function year(v: unknown, consecutive = true): v is string {
  return (
    string(v) &&
    fullMatch(/\d{4}-\d{4}/, v) &&
    (!consecutive || Number(v.slice(5)) === Number(v.slice(0, 4)) + 1)
  );
}
