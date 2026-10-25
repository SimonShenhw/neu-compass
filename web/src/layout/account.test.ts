import { expect, it } from 'vitest';
import { GUEST } from '../api/queries';
import type { Member } from '../api/queries';
import { viewerOwner, viewerScope } from './account';

const member: Member = {
  kind: 'member',
  userId: 'u-1',
  email: 'synthetic.student@husky.neu.edu',
  displayName: null,
  contributionCount: 1,
};

it('who is asking, for a key: nobody yet, unsure, a guest, or a member with their count', () => {
  expect(viewerScope({ viewer: undefined, unsure: false })).toBeNull();
  expect(viewerScope({ viewer: undefined, unsure: true })).toBe('unsure');
  expect(viewerScope({ viewer: GUEST, unsure: false })).toBe('guest');
  expect(viewerScope({ viewer: member, unsure: false })).toBe('member:u-1:1');
  expect(
    viewerScope({ viewer: { ...member, contributionCount: 2 }, unsure: false }),
  ).toBe('member:u-1:2');
  expect(
    viewerScope({ viewer: { ...member, userId: 'u-2' }, unsure: false }),
  ).toBe('member:u-2:1');
});

it('who the page is for leaves the level out', () => {
  expect(viewerOwner(undefined)).toBe('guest');
  expect(viewerOwner(GUEST)).toBe('guest');
  expect(viewerOwner(member)).toBe('member:u-1');
  expect(viewerOwner({ ...member, contributionCount: 2 })).toBe('member:u-1');
  expect(viewerOwner({ ...member, userId: 'u-2' })).toBe('member:u-2');
});
