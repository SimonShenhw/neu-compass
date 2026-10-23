// R5b's view contract. The course detail is the API's own shape (generated, R2b); the rest is the page's.
import type { Schemas } from './types';

export type CourseDetail = Schemas['CourseDetailOut'];
export type CompareColumn =
  | { status: 'loading' }
  | { status: 'error'; httpStatus: number | null }
  | { status: 'ready'; body: unknown };
export interface ComparePageProps {
  ids: readonly string[];
  columns: Readonly<Record<string, CompareColumn>>;
  onRemove: (id: string) => void;
  onClear: () => void;
  onReload: () => void;
}
