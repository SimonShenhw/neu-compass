import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  CAPTURE_LABEL,
  CAPTURE_OFF,
  QUERY_LOG_FALLBACK,
} from '../layout/AskBar';
import { SHARE_NOTE } from '../pages/CourseRoute';
import {
  PLAN_NOTE,
  PLAN_REVISED,
  PLANS_UNAVAILABLE,
  PROGRAM_NOTE,
  PROGRAMS_UNAVAILABLE,
} from '../pages/SearchRoute';

// The words the search and course pages copy from Streamlit and the API (R3e), checked against the Python they come
// from, so a change on either side shows here (review B32). The Python is there only in a whole checkout: the mutation
// scripts' snapshots copy web/ alone, and skip these.
const repo = resolve(process.cwd(), '..');
const whole = existsSync(resolve(repo, 'app', 'streamlit_app.py'));

describe.skipIf(!whole)('words copied from the Python side', () => {
  it.each([
    ['api/privacy_text.py', QUERY_LOG_FALLBACK],
    ['app/answer_feedback_view.py', CAPTURE_OFF],
    ['app/answer_feedback_view.py', CAPTURE_LABEL],
    ['app/streamlit_app.py', PROGRAMS_UNAVAILABLE],
    ['app/program_plan_view.py', PROGRAM_NOTE],
    ['app/chat_plan_view.py', PLANS_UNAVAILABLE],
    ['app/chat_plan_view.py', PLAN_REVISED],
    ['app/chat_plan_view.py', PLAN_NOTE],
    ['app/course_detail_view.py', SHARE_NOTE],
  ])('%s says %s', (file, words) => {
    expect(readFileSync(resolve(repo, file), 'utf8')).toContain(words);
  });
});
