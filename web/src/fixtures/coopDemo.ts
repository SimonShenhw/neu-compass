import { ApiError, failureFrom } from '../api/client';
import { submitFailure } from '../api/coop';
import type {
  CoopListState,
  CoopRecord,
  CoopViewer,
  SubmitOutcome,
} from '../api/coop';
import guest from './coop/list-guest.json';
import member0 from './coop/list-member-0.json';
import member1 from './coop/list-member-1.json';
import member2 from './coop/list-member-2.json';
import empty from './coop/list-empty.json';
import pending from './coop/upload-pending.json';
import dupPending from './coop/upload-duplicate-pending.json';
import approved from './coop/upload-duplicate-approved.json';
import published from './coop/upload-duplicate-published.json';
import rejected from './coop/upload-duplicate-rejected.json';
import unauthorized from './coop/upload-401-unknown-user.json';
import invalid from './coop/upload-422-duration.json';
import unavailable from './coop/upload-503-no-moderation.json';

const viewers = {
  guest: {
    label: '游客',
    viewer: { kind: 'guest' },
    records: guest.body as CoopRecord[],
  },
  member0: {
    label: '会员 · 0 条贡献',
    viewer: { kind: 'member', contributionCount: 0 },
    records: member0.body as CoopRecord[],
  },
  member1: {
    label: '会员 · 1 条贡献',
    viewer: { kind: 'member', contributionCount: 1 },
    records: member1.body as CoopRecord[],
  },
  member2: {
    label: '会员 · 2 条贡献',
    viewer: { kind: 'member', contributionCount: 2 },
    records: member2.body as CoopRecord[],
  },
} satisfies Record<
  string,
  { label: string; viewer: CoopViewer; records: CoopRecord[] }
>;
export const viewerOptions = Object.entries(viewers).map(([value, data]) => ({
  value,
  label: data.label,
}));
export function readViewer(value: string | null): keyof typeof viewers {
  return value && Object.hasOwn(viewers, value)
    ? (value as keyof typeof viewers)
    : 'guest';
}
export function demoViewer(value: keyof typeof viewers): CoopViewer {
  return viewers[value].viewer;
}
export const listOptions = [
  { value: 'ready', label: '正常列表' },
  { value: 'loading', label: '加载中' },
  { value: 'error', label: '加载失败' },
  { value: 'empty', label: '空列表' },
];
export function demoList(
  viewer: keyof typeof viewers,
  state: string | null,
): CoopListState {
  if (state === 'loading' || state === 'error') return { status: state };
  return {
    status: 'ready',
    records: (state === 'empty'
      ? empty.body
      : viewers[viewer].records) as CoopRecord[],
  };
}
const results = {
  pending,
  'duplicate-pending': dupPending,
  'duplicate-approved': approved,
  'duplicate-published': published,
  'duplicate-rejected': rejected,
};
export const submitOptions = [
  ...Object.keys(results).map((value) => ({ value, label: value })),
  ...['401', '422', '503', 'network'].map((value) => ({ value, label: value })),
];
// A failed upload read from the fixture's answer the way the live page reads one: R2b's failureFrom keeps the status,
// error_type and the refused fields, never the detail text (R5d).
function failed(fixture: { status: number; body: unknown }): SubmitOutcome {
  const text = JSON.stringify(fixture.body);
  return submitFailure(
    failureFrom(new Response(text, { status: fixture.status }), text),
  );
}
export function demoOutcome(value: string | null): SubmitOutcome {
  if (value === 'network')
    return submitFailure(new ApiError(503, { errorType: 'transport_error' }));
  if (value === '401') return failed(unauthorized);
  if (value === '422') return failed(invalid);
  if (value === '503') return failed(unavailable);
  const key =
    value && Object.hasOwn(results, value)
      ? (value as keyof typeof results)
      : 'pending';
  return {
    ok: true,
    result: results[key].body as Extract<SubmitOutcome, { ok: true }>['result'],
  };
}
