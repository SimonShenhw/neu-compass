import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { render } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { courseDetailFixture } from '../../fixtures/courseDetailDemo';
import { CourseDetail } from './CourseDetail';
import { expandDetail, readDetail } from './detailTestUtils';
import type { DetailEvent } from './detailTestUtils';

interface Golden {
  case: string;
  scenarios: { name: string; compare: string[]; visible: DetailEvent[] }[];
}
const directory = resolve('src/fixtures/course-detail/expected');
const goldens = readdirSync(directory).map(
  (file) =>
    JSON.parse(readFileSync(resolve(directory, file), 'utf8')) as Golden,
);
const scenarios = goldens.flatMap((g) =>
  g.scenarios.map((s) => ({ caseName: g.case, ...s })),
);
it('freezes all nine detail exports and twelve golden scenarios', () => {
  expect(goldens).toHaveLength(9);
  expect(scenarios).toHaveLength(12);
});
it.each(scenarios)(
  'detail golden $caseName / $name exact content order links tooltip and disclosure depths',
  async (scenario) => {
    const { container } = render(
      <CourseDetail
        course={courseDetailFixture(scenario.caseName).body}
        compare={scenario.compare}
        onAddToCompare={vi.fn()}
        onOpenCourse={vi.fn()}
      />,
    );
    await expandDetail(container);
    expect(readDetail(container)).toEqual(scenario.visible);
  },
);
