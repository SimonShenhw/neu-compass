import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { render } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { requisitesFixture } from '../../fixtures/requisitesDemo';
import { CourseRequisites, YEAR_EMPTY, YEAR_LABEL } from './CourseRequisites';
import { PLAN_LABEL } from './ProgramContextPanel';
import { choose, expandAll, readVisible } from './requisitesTestUtils';
import type { Visible } from './requisitesTestUtils';

interface Golden {
  case: string;
  scenarios: {
    name: string;
    year: string | null;
    plan: string | null;
    cleared: boolean;
    visible: Visible[];
  }[];
}
const directory = resolve('src/fixtures/requisites/expected');
export const goldens = readdirSync(directory).map(
  (name) =>
    JSON.parse(readFileSync(resolve(directory, name), 'utf8')) as Golden,
);
const scenarios = goldens.flatMap((golden) =>
  golden.scenarios.map((scenario) => ({ caseName: golden.case, ...scenario })),
);
it('freezes all 16 cases and all 34 golden choice scenarios', () => {
  expect(goldens).toHaveLength(16);
  expect(scenarios).toHaveLength(34);
});
it.each(scenarios)(
  'golden $caseName / $name preserves exact order text kinds and depths',
  async (scenario) => {
    const fixture = requisitesFixture(scenario.caseName);
    const onOpen = vi.fn();
    const { container } = render(
      <CourseRequisites
        course={fixture.body}
        requisites={fixture.body.course_requisites}
        prerequisites={fixture.body.prerequisites}
        onOpenCourse={onOpen}
      />,
    );
    if (scenario.cleared) await choose(YEAR_LABEL, YEAR_EMPTY);
    else if (scenario.year)
      await choose(
        YEAR_LABEL,
        `Catalog ${scenario.year}（校区和个人路径未声明）`,
      );
    await expandAll(container);
    if (scenario.plan) {
      const expectedSelect = scenario.visible.find(
        (v) => v.kind === 'select' && v.label === PLAN_LABEL,
      )!;
      await choose(PLAN_LABEL, expectedSelect.chosen!);
      await expandAll(container);
    }
    expect(await readVisible(container)).toEqual(scenario.visible);
    expect(onOpen).not.toHaveBeenCalled();
  },
);
