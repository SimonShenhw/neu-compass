// A course's page on the live API (R3e). /course/CS-6140 names the course by its code (models/coursePath.ts): resolved
// with /resolve/course, unless a link inside the site handed the course ID along. The detail is R3b's CourseDetail, R3a's
// requisites panel inside it, from one GET /course/{id}; 「加入对比」 adds the course to the comparison (R5b's list); the
// share box gives this page's address on the site shared links name. Beside it, the search column (SearchWorkspace).
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { useRef } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { apiErrorMessage, isJsonObject, isTransientError } from '../api/client';
import { courseQuery } from '../api/course';
import { failureOf } from '../api/load';
import { shownData } from '../api/queries';
import { resolveQuery } from '../api/resolve';
import type { ResolvedCourse } from '../api/resolve';
import { Button } from '../components/Button';
import { CourseDetail } from '../features/course-detail/CourseDetail';
import {
  DetailDisclosure,
  DetailText,
} from '../features/course-detail/DetailPrimitives';
import { addToCompare, useCompareList } from '../models/compareList';
import { oneLine } from '../models/courseDetailFormat';
import { codeFromPath, courseShareUrl, refLabel } from '../models/coursePath';
import { SearchWorkspace, useOpenCourse } from './SearchRoute';
import styles from './CourseRoute.module.css';

// Streamlit's ?course= sentences (app/deep_links.py), without the emoji and the Markdown.
export const notFound = (label: string) =>
  `链接指向的课程「${label}」没找到：可能已经停开，或者链接被截断了。`;
export const SHARE_NOTE = '把链接发给同学，他们打开就直接看到这门课。';
// Streamlit lists at most three other courses a code also names.
const OTHERS = 3;

// The course ID a link inside the site handed along (SearchRoute's useOpenCourse), or null: only one the API's path can
// carry (apiPath refuses "", "." and ".."), so anything else is looked up by its code instead (review A32).
function knownId(state: unknown): string | null {
  return isJsonObject(state) &&
    typeof state.courseId === 'string' &&
    !['', '.', '..'].includes(state.courseId)
    ? state.courseId
    : null;
}

function Retry({ onRetry }: { onRetry: () => void }) {
  return (
    <Button size="sm" onClick={onRetry}>
      重新加载
    </Button>
  );
}

function Detail({
  courseId,
  segment,
  others,
  keepFocus,
}: {
  courseId: string;
  segment: string;
  others: readonly ResolvedCourse[];
  keepFocus: () => void;
}) {
  const detail = useQuery(courseQuery(courseId));
  const compare = useCompareList();
  const openCourse = useOpenCourse();
  const body = shownData(detail);
  if (body === undefined) {
    if (!detail.isError || detail.isFetching)
      return <p role="status">正在加载课程详情…</p>;
    const failure = failureOf(detail.error);
    return (
      <div className={styles.state}>
        <DetailText kind="warning">
          {failure.status === 404
            ? '找不到这门课的详情，可能已经下线。'
            : `无法加载课程详情。${apiErrorMessage(failure)}`}
        </DetailText>
        {isTransientError(failure) && (
          <Retry
            onRetry={() => {
              keepFocus();
              void detail.refetch();
            }}
          />
        )}
      </div>
    );
  }
  const code =
    isJsonObject(body) && typeof body.primary_code === 'string'
      ? body.primary_code
      : codeFromPath(segment);
  return (
    <>
      {others.length > 0 && (
        <div
          role="group"
          className={styles.others}
          aria-label="同一个课号的其他课程"
        >
          <DetailText kind="note">
            {`「${refLabel(codeFromPath(segment))}」对应多门课程，已打开 ${oneLine(code)}；其他：`}
          </DetailText>
          <div className={styles.links}>
            {others.slice(0, OTHERS).map((course) => (
              <Button
                key={course.course_id}
                size="sm"
                onClick={() =>
                  openCourse(course.course_id, course.primary_code)
                }
              >
                {`${oneLine(course.primary_code)} · ${oneLine(course.primary_name)}`}
              </Button>
            ))}
          </div>
        </div>
      )}
      <CourseDetail
        course={body}
        compare={compare}
        onAddToCompare={(id) => void addToCompare(id)}
        onOpenCourse={(next) => openCourse(null, next)}
      />
      <DetailDisclosure label="分享这门课">
        <input
          className={styles.share}
          readOnly
          value={courseShareUrl(code)}
          aria-label="这门课的链接"
          onFocus={(event) => event.currentTarget.select()}
        />
        <DetailText kind="note">{SHARE_NOTE}</DetailText>
      </DetailDisclosure>
    </>
  );
}

function CoursePanel({
  segment,
  known,
}: {
  segment: string;
  known: string | null;
}) {
  const resolve = useQuery({
    ...resolveQuery(segment),
    enabled: known === null,
  });
  const label = refLabel(codeFromPath(segment));
  // 重新加载 goes as the detail or the code's lookup loads again: focus goes to the panel, which stays, without
  // scrolling (R6).
  const panel = useRef<HTMLDivElement>(null);
  const keepFocus = () => panel.current?.focus({ preventScroll: true });
  let content;
  if (known !== null)
    content = (
      <Detail
        courseId={known}
        segment={segment}
        others={[]}
        keepFocus={keepFocus}
      />
    );
  else {
    const matches = shownData(resolve);
    if (matches === undefined) {
      if (!resolve.isError || resolve.isFetching)
        content = <p role="status">{`正在查找 ${label}…`}</p>;
      else {
        const failure = failureOf(resolve.error);
        // A ref the API refuses as too long (422) names no course; a failure for a moment can be tried again.
        content = isTransientError(failure) ? (
          <div className={styles.state}>
            <DetailText kind="warning">
              {`链接里的课程暂时打不开。${apiErrorMessage(failure)}`}
            </DetailText>
            <Retry
              onRetry={() => {
                keepFocus();
                void resolve.refetch();
              }}
            />
          </div>
        ) : (
          <DetailText kind="warning">{notFound(label)}</DetailText>
        );
      }
    } else if (matches.length === 0)
      content = <DetailText kind="warning">{notFound(label)}</DetailText>;
    else
      content = (
        <Detail
          courseId={matches[0]!.course_id}
          segment={segment}
          others={matches.slice(1)}
          keepFocus={keepFocus}
        />
      );
  }
  // No landmark of its own: the detail inside is the region 「课程详情」 (R3b). A group named as the address names the
  // course (its code, or a short name such as ML that names several), so the place focus goes after 重新加载 says what
  // it is (review A34).
  return (
    <div
      ref={panel}
      role="group"
      aria-label={label}
      tabIndex={-1}
      className={styles.panel}
    >
      <Link to="/" className={styles.back}>
        <ArrowLeft aria-hidden="true" />
        回到课程搜索
      </Link>
      {content}
    </div>
  );
}

export function CourseRoute() {
  const { code: segment = '' } = useParams();
  const { state } = useLocation();
  const known = knownId(state);
  return (
    <SearchWorkspace
      detail={
        <CoursePanel
          key={`${segment}\n${known ?? ''}`}
          segment={segment}
          known={known}
        />
      }
    />
  );
}
