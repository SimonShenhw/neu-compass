// What a page knows of who is looking, and the account actions a page needs (R5d). AppShell provides it from
// useSession, the same session the account box shows; a page reads it with useAccount().
import { createContext, useContext } from 'react';
import type { Viewer } from '../api/queries';

export interface Account {
  // undefined until /auth/me has answered. unsure: it failed for a moment, so a member may be shown as a guest.
  viewer: Viewer | undefined;
  unsure: boolean;
  login: () => void;
  // The account is gone (deleted, or the deletion's login no longer works): the page forgets who it was, as a logout
  // does, without asking the API, which has expired the cookie already.
  signedOut: () => Promise<void>;
  // The contribution count an upload's 201 gives, which is the server's (R0 8: never inferred as one more).
  contributed: (count: number) => Promise<void>;
}

export const AccountContext = createContext<Account | null>(null);

export function useAccount(): Account {
  const account = useContext(AccountContext);
  if (!account) throw new Error('AccountContext is required');
  return account;
}

// The part of a query key that says who is asking, for an answer that depends on it (the Co-op list; R0 14.9). null
// while nobody knows yet: such a query waits. A viewer /auth/me could not confirm is asked about as 'unsure', since
// the API goes by the cookie either way. A member's key changes with the contribution count, which decides what the
// API shows.
export function viewerScope({
  viewer,
  unsure,
}: Pick<Account, 'viewer' | 'unsure'>): string | null {
  if (viewer === undefined) return unsure ? 'unsure' : null;
  return viewer.kind === 'guest'
    ? 'guest'
    : `member:${viewer.userId}:${viewer.contributionCount}`;
}

// Who the page is for, without the level: a page keyed by it starts afresh for another person (drafts and opened
// details go), not when the same person's level changes.
export function viewerOwner(viewer: Viewer | undefined): string {
  return viewer?.kind === 'member' ? `member:${viewer.userId}` : 'guest';
}
