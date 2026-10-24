import { useQueries } from '@tanstack/react-query';
import { answerStatus } from '../api/client';
import { courseQuery } from '../api/course';
import type { CompareColumn } from '../api/course';
import { shownData } from '../api/queries';
import { resolveColumn } from '../models/compare';
import {
  MAX_COMPARE_COURSES,
  clearCompare,
  removeFromCompare,
  useCompareList,
} from '../models/compareList';
import { ComparePage } from './ComparePage';

// One course's column from its query: what can be shown (a temporary failure keeps the last answer), a retry or the
// first try still going, or the failure (null: no answer came; R5b).
export function compareColumn(query: {
  data: unknown;
  error: unknown;
  isFetching: boolean;
}): CompareColumn {
  const shown = shownData(query);
  if (shown !== undefined) return { status: 'ready', body: shown };
  if (query.error && !query.isFetching)
    return { status: 'error', httpStatus: answerStatus(query.error) };
  return { status: 'loading' };
}

// /compare on the live API (R5d): GET /course/{course_id} for each course in the list, asked again on every visit as
// Streamlit's page does (nothing is fresh for long). The page itself is R5b's; adding courses is the course detail's
// (R3).
export function CompareRoute() {
  const ids = useCompareList();
  const selected = ids.slice(0, MAX_COMPARE_COURSES);
  const queries = useQueries({
    queries: selected.map((id) => ({ ...courseQuery(id), staleTime: 0 })),
  });
  const columns: Record<string, CompareColumn> = Object.fromEntries(
    selected.map((id, index) => [id, compareColumn(queries[index]!)]),
  );
  return (
    <ComparePage
      ids={ids}
      columns={columns}
      onRemove={removeFromCompare}
      onClear={clearCompare}
      // Only the columns that failed are asked again, Streamlit's 重新加载 (a column the page could not read counts).
      onReload={() =>
        selected.forEach((id, index) => {
          if (resolveColumn(columns[id]).status === 'error')
            void queries[index]!.refetch();
        })
      }
    />
  );
}
