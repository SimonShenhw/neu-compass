import { useQuery } from '@tanstack/react-query';
import { answerStatus } from '../api/client';
import { deleteAccount, privacyQuery } from '../api/privacy';
import type { DeleteOutcome, PrivacyState } from '../api/privacy';
import { shownData, stillSignedInAs } from '../api/queries';
import { useAccount } from '../layout/account';
import { PrivacyPage } from './PrivacyPage';

// /privacy on the live API (R5d): the API's own words, and deleting the account. The page itself is R5c's. It is not
// keyed by the viewer: the deletion's result stays on screen after the page becomes a guest's (R5c 4).
export function PrivacyRoute() {
  const { viewer, signedOut } = useAccount();
  const query = useQuery(privacyQuery);
  const body = shownData(query);
  const privacy: PrivacyState =
    body !== undefined
      ? { status: 'ready', body }
      : query.error && !query.isFetching
        ? { status: 'error', httpStatus: answerStatus(query.error) }
        : { status: 'loading' };
  // Only the account this page shows is deleted: when another tab has since logged out, or in as someone else, nothing
  // is sent and the answer is a login that no longer works. After a 200 or a 401 the account is gone (or this login
  // is), whether or not the page is still there to say so: R5c drops an answer that comes after the page or its form
  // went, so the route forgets who was looking itself, once the page has had its turn to show the answer (A27).
  async function remove(): Promise<DeleteOutcome> {
    const outcome: DeleteOutcome = (await stillSignedInAs(viewer))
      ? await deleteAccount()
      : { ok: false, status: 401 };
    if (outcome.ok || outcome.status === 401)
      setTimeout(() => void signedOut(), 0);
    return outcome;
  }
  return (
    <PrivacyPage
      viewer={
        viewer?.kind === 'member' ? { kind: 'member' } : { kind: 'guest' }
      }
      privacy={privacy}
      onRetry={() => void query.refetch()}
      onDelete={remove}
      // The route signs out after every 200 and 401 (above), so the page's own call has nothing left to do.
      onSignedOut={() => undefined}
    />
  );
}
