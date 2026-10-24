import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import type { FeedbackVote } from '../../api/chat';
import { SearchConversation } from './SearchConversation';
import {
  defaultDisclosures,
  expandSearch,
  readSearch,
  scenarios,
  settledTurns,
} from './searchTestUtils';

it('freezes 34 search conversations and 50 golden scenarios', () => {
  expect(new Set(scenarios.map((s) => s.caseName)).size).toBe(34);
  expect(scenarios).toHaveLength(50);
});
it.each(scenarios)(
  'search golden $caseName / $name exact DOM order depth defaults links buttons and course IDs',
  async (scenario) => {
    let clickIndex = 0;
    const onFeedback = vi.fn<(vote: FeedbackVote) => Promise<unknown>>(
      async () => {
        const outcome = scenario.clicks[clickIndex++]!.outcome;
        if (typeof outcome === 'number')
          throw {
            status: outcome,
            errorType: null,
            retryAfter: null,
            invalidFields: [],
            reason: null,
          };
        return outcome;
      },
    );
    const turns = settledTurns(scenario);
    const { container } = render(
      <SearchConversation
        turns={turns}
        busy={false}
        feedbackEnabled={scenario.feedback_enabled}
        onFeedback={onFeedback}
        onViewCourse={vi.fn()}
        onFollowUp={vi.fn()}
      />,
    );
    if (
      scenario.visible.some((e) => e.kind === 'button' && e.text === '有帮助')
    )
      await screen.findByRole('button', { name: '有帮助' });
    for (const click of scenario.clicks) {
      await userEvent.setup().click(
        screen.getByRole('button', {
          name: click.rating === 'up' ? '有帮助' : '没帮助',
        }),
      );
      await waitFor(() =>
        expect(
          screen.getByRole('region', { name: '回答反馈' }),
        ).toHaveAttribute('aria-busy', 'false'),
      );
    }
    const defaults = defaultDisclosures(container);
    await expandSearch(container);
    expect(readSearch(container, defaults)).toEqual(scenario.visible);
    expect(onFeedback).toHaveBeenCalledTimes(scenario.clicks.length);
    scenario.clicks.forEach((click, i) => {
      expect(Object.keys(onFeedback.mock.calls[i]![0] ?? {}).sort()).toEqual([
        'answer_id',
        'answer_sha256',
        'feedback_token',
        'rating',
      ]);
      expect(onFeedback.mock.calls[i]![0]).toMatchObject({
        rating: click.rating,
      });
    });
  },
);
