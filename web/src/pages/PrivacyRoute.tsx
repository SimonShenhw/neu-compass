import { useQuery } from '@tanstack/react-query';
import { answerStatus } from '../api/client';
import { deleteAccount, privacyQuery } from '../api/privacy';
import type { PrivacyState } from '../api/privacy';
import { shownData } from '../api/queries';
import { useAccount } from '../layout/account';
import { PrivacyPage } from './PrivacyPage';

// /privacy on the live API (R5d): the API's own words, and deleting the account. The page itself is R5c's. It is not
// keyed by the viewer: the deletion's result stays on screen after the page becomes a guest's (R5c 4).
export function PrivacyRoute() {
  const account = useAccount();
  const query = useQuery(privacyQuery);
  const body = shownData(query);
  const privacy: PrivacyState =
    body !== undefined
      ? { status: 'ready', body }
      : query.error && !query.isFetching
        ? { status: 'error', httpStatus: answerStatus(query.error) }
        : { status: 'loading' };
  return (
    <PrivacyPage
      viewer={
        account.viewer?.kind === 'member'
          ? { kind: 'member' }
          : { kind: 'guest' }
      }
      privacy={privacy}
      onRetry={() => void query.refetch()}
      onDelete={deleteAccount}
      onSignedOut={() => void account.signedOut()}
    />
  );
}
