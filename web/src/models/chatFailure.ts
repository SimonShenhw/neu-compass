import type { ChatFailure } from '../api/chat';
import { integer, object, string, strings } from './searchGuard';

export const UNKNOWN_FAILURE: ChatFailure = {
  status: 0,
  errorType: null,
  retryAfter: null,
  invalidFields: [],
  reason: null,
};
export function isChatFailure(v: unknown): v is ChatFailure {
  return (
    object(v) &&
    integer(v.status, 100, 599) &&
    (v.errorType === null || string(v.errorType)) &&
    (v.reason === null || string(v.reason)) &&
    (v.retryAfter === null || typeof v.retryAfter === 'number') &&
    strings(v.invalidFields) !== null
  );
}
const planRetry =
  '，这个问题还没有回答；方案选择已清除。可以在「方案」里重新选择后再问，或不选方案直接再问。';
const conflicts = new Map([
  ['plan_missing', '所选方案已不可用' + planRetry],
  ['plan_stale', '所选方案的范围或内容版本已变化' + planRetry],
  ['plan_draft', '所选方案尚未完成来源对照' + planRetry],
  ['plan_unusable', '所选方案的身份、范围或格式无法确认' + planRetry],
  [
    'plan_unavailable',
    '暂时无法核对所选方案，这个问题还没有回答；方案选择已清除。可以先不选方案直接再问，稍后再到「方案」里选择。',
  ],
  [
    'program_ambiguous',
    '问题里的专业前缀对应好几个项目，这个问题还没有回答。请先在「项目」里选一个，再问一次。',
  ],
  [
    'program_conflict',
    '「项目」里选的项目和问题里的专业前缀不一致，这个问题还没有回答。请把「项目」改回「不指定」，或者改写问题。',
  ],
]);
export function chatFailureMessage(failure: ChatFailure): string {
  const { status, reason, errorType, retryAfter, invalidFields } = failure;
  if (status === 409)
    return (
      conflicts.get(reason ?? '') ??
      '这个问题和所选的项目或方案对不上，还没有回答。请检查「项目」和「方案」，或者改写问题后再问。'
    );
  if (status === 404)
    return '所选的项目已经不存在，这个问题还没有回答。请在「项目」里重新选择，或者改回「不指定」再问。';
  if (status === 422)
    return invalidFields.includes('query')
      ? '问题最多 500 个字，这个问题没有发出去。请改短一点再问。'
      : '这次提问的格式不对，没有发出去。请改一下再问。';
  const delay =
    retryAfter !== null && Number.isFinite(retryAfter)
      ? `${retryAfter} 秒后`
      : '稍后';
  if (status === 429) return `请求过于频繁，请${delay}手动重试。`;
  if (status === 503)
    return `${errorType === 'service_busy' ? '服务正忙' : '服务暂不可用'}，请${delay}手动重试。`;
  if (status === 408 || status === 504)
    return '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。';
  if (status === 502 && errorType === 'invalid_response')
    return '服务返回了无法识别的内容，请稍后手动重试。';
  if (status >= 500 && status <= 599) return '服务暂时出错，请稍后手动重试。';
  return '请求未完成，请稍后手动重试。';
}
