// GET /resolve/course (R3e): a course page's address, or an old ?course= link, as the courses it names, most specific
// first, none for a dead link, which is an answer and not an error (api/routes/resolve.py). The ref is a course the
// student opened: it stays in this tab's query cache and is never logged (R0 14.1).
import { queryOptions } from '@tanstack/react-query';
import { apiGet, apiPath, isJsonObject, unreadableAnswer } from './client';
import { PUBLIC_FRESH_MS } from './queries';

export interface ResolvedCourse {
  course_id: string;
  primary_code: string;
  primary_name: string;
}

const text = (value: unknown): value is string =>
  typeof value === 'string' && value.trim() !== '';

// The matches, each checked; one that is not a course makes the whole answer unreadable, as R2b's parsers do.
export function parseResolved(value: unknown): ResolvedCourse[] {
  if (!isJsonObject(value) || !Array.isArray(value.matches))
    throw unreadableAnswer();
  return value.matches.map((match: unknown) => {
    if (
      !isJsonObject(match) ||
      !text(match.course_id) ||
      !text(match.primary_code) ||
      typeof match.primary_name !== 'string'
    )
      throw unreadableAnswer();
    return {
      course_id: match.course_id,
      primary_code: match.primary_code,
      primary_name: match.primary_name,
    };
  });
}

export function resolveQuery(ref: string) {
  return queryOptions({
    queryKey: ['resolve', ref],
    queryFn: async ({ signal }) =>
      parseResolved(
        await apiGet(apiPath('/resolve/course'), {
          timeout: 'read',
          signal,
          query: { ref },
        }),
      ),
    staleTime: PUBLIC_FRESH_MS,
  });
}
