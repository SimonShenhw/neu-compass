import { useQuery } from '@tanstack/react-query';
import { coopListQuery, submitFailure, uploadCoop } from '../api/coop';
import type {
  CoopListState,
  CoopUploadRequest,
  CoopViewer,
  SubmitOutcome,
} from '../api/coop';
import { shownData } from '../api/queries';
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
