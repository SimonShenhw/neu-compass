import { render, cleanup, screen } from '@testing-library/react';
import { it, expect, vi } from 'vitest';
import {
  shareUrl,
  collapseSpace,
  scopeLabel,
  requirementLabel,
  semesterHeading,
  capturedText,
} from './programFormat';
import type { SharePlan } from './programFormat';
import type { ApiFailure } from '../api/load';
import shares from '../fixtures/programs/expected/share-url-vectors.json';
import spaces from '../fixtures/programs/expected/collapse-space-vectors.json';
import failures from '../fixtures/programs/expected/failure-vectors.json';
import { ProgramList } from '../features/programs/ProgramList';
import { ProgramCurriculum } from '../features/programs/ProgramCurriculum';
import { curriculumProps } from '../features/programs/programTestUtils';
it.each(shares.map((v, i) => ({ ...v, i })))(
  'share URL vector $i matches: a program at its own address, a plan as Python urlencode writes it',
  (v) =>
    expect(shareUrl(v.base, v.program_id, v.link as SharePlan | null)).toBe(
      v.url,
    ),
);
it.each(spaces.map((v, i) => ({ ...v, i })))(
  'whitespace vector $i matches Python split',
  (v) => expect(collapseSpace(v.text)).toBe(v.collapsed),
);
it.each(failures.map((v, i) => ({ ...v, i })))(
  'failure vector $i matches full list and curriculum lines',
  (v) => {
    const failure = v.failure as ApiFailure;
    render(
      <ProgramList
        programs={{ status: 'failed', failure }}
        onOpenProgram={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(v.list);
    cleanup();
    render(
      <ProgramCurriculum
        {...curriculumProps()}
        curriculum={{ status: 'failed', failure }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(v.curriculum);
  },
);
it('small formatting helpers preserve exact source semantics', () => {
  expect(
    scopeLabel({
      program_id: 'x',
      campus: 'boston',
      catalog_year: '2026-2027',
      pathway: 'bridge',
      concentration: null,
    }),
  ).toBe(
    'boston · Catalog 2026-2027 · Bridge · 共同部分／未限定 concentration',
  );
  expect(
    [
      'core',
      'foundation',
      'elective_pool',
      'capstone',
      'unknown',
      '__proto__',
      'constructor',
    ].map(requirementLabel),
  ).toEqual([
    '核心 · core',
    '基础 · foundation',
    '选修池 · elective',
    '毕业项目 · capstone',
    '基础 · foundation',
    '基础 · foundation',
    '基础 · foundation',
  ]);
  expect(semesterHeading(2)).toBe('旧课程表：第 2 学期建议（未核验）');
  expect(semesterHeading(null)).toBe('未提供推荐学期（不等于任意学期都可修）');
  expect(capturedText('2026-10-02T10:00:00.123456Z')).toBe(
    '2026-10-02T10:00:00.123456+00:00',
  );
  expect(capturedText('unchanged')).toBe('unchanged');
});
