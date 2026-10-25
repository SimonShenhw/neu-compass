import { useQuery } from '@tanstack/react-query';
import { coopListQuery, submitFailure, uploadCoop } from '../api/coop';
import type {
  CoopListState,
  CoopUploadRequest,
  CoopViewer,
  SubmitOutcome,
} from '../api/coop';
import { shownData, signedInNow } from '../api/queries';
import { useAccount, viewerOwner, viewerScope } from '../layout/account';
import { CoopPage } from './CoopPage';

// /coop on the live API (R5d): the list as this viewer may see it, and the upload. The page itself is R5a's.
export function CoopRoute() {
  const account = useAccount();
  const scope = viewerScope(account);
  const list = useQuery({
    ...coopListQuery(scope ?? 'pending'),
    enabled: scope !== null,
  });
  if (scope === null)
    return (
      <p role="status" aria-label="Co-op 加载">
        正在加载
      </p>
    );
  // A page that shows a guest gets the rows as a guest is shown them, whatever the cookie unlocks (coopListQuery).
  const records = shownData(list);
  const state: CoopListState =
    records !== undefined
      ? { status: 'ready', records }
      : list.isError && !list.isFetching
        ? { status: 'error' }
        : { status: 'loading' };
  const viewer: CoopViewer =
    account.viewer?.kind === 'member'
      ? { kind: 'member', contributionCount: account.viewer.contributionCount }
      : { kind: 'guest' };
  async function submit(request: CoopUploadRequest): Promise<SubmitOutcome> {
    // An upload counts for whoever the cookie belongs to now: when another tab has since logged out, or in as someone
    // else, it is not sent, and the form says this login no longer works, keeping the draft (A27).
    if ((await signedInNow(account.viewer)) === 'other')
      return {
        ok: false,
        status: 401,
        errorType: 'unauthorized',
        invalidFields: [],
      };
    let result;
    try {
      result = await uploadCoop(request);
    } catch (error) {
      return submitFailure(error);
    }
    // The server's count, which may have grown since login if a reviewer published an earlier upload.
    await account.contributed(result.contribution_count);
    return { ok: true, result };
  }
  return (
    <CoopPage
      key={viewerOwner(account.viewer)}
      viewer={viewer}
      list={state}
      onRetryList={() => void list.refetch()}
      onSubmit={submit}
      onLogin={account.login}
    />
  );
}
