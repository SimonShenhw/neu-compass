import type { DeleteOutcome, PrivacySection } from '../api/privacy';

type PrivacyContent = {
  intro: string;
  sections: PrivacySection[];
  delete_what: string;
};
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
// Validate everything before displaying any policy. Unused API fields stay unused.
export function privacyContent(value: unknown): PrivacyContent | null {
  if (
    !isObject(value) ||
    typeof value.intro !== 'string' ||
    typeof value.delete_what !== 'string' ||
    !Array.isArray(value.sections) ||
    value.sections.length === 0
  )
    return null;
  const sections: PrivacySection[] = [];
  for (const section of value.sections) {
    if (
      !isObject(section) ||
      typeof section.heading !== 'string' ||
      !Array.isArray(section.sentences) ||
      !section.sentences.every(
        (sentence): sentence is string => typeof sentence === 'string',
      )
    )
      return null;
    sections.push({ heading: section.heading, sentences: section.sentences });
  }
  return { intro: value.intro, delete_what: value.delete_what, sections };
}
export const deleteMessages = {
  success:
    '你的账号和 Co-op 投稿已经删除，本页已登出。每日备份里的副本最多再留大约两周。',
  expired: '这个登录已经失效，本页已登出。如果账号还在，请重新登录以后再删除。',
  // User-approved R5c correction: guest status alone is not proof of deletion.
  uncertain:
    '这次没收到服务器的确认，不确定删除有没有完成。刷新后若仍是登录状态，可以再试；若已变成游客但需要确认，请联系维护者。',
  refused: '删除没有完成，什么也没删。请稍后再试；一直不行的话，请写邮件联系。',
} as const;
export function deletionNotice(outcome: DeleteOutcome): {
  message: string;
  signedOut: boolean;
} {
  if (outcome.ok) return { message: deleteMessages.success, signedOut: true };
  if (outcome.status === 401)
    return { message: deleteMessages.expired, signedOut: true };
  return {
    message:
      outcome.status === null || [502, 503, 504].includes(outcome.status)
        ? deleteMessages.uncertain
        : deleteMessages.refused,
    signedOut: false,
  };
}
