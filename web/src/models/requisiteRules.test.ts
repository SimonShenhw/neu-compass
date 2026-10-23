import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
import type { ProgramNode, RequisiteNode } from '../api/requisites';
import { requisitesFixtures } from '../fixtures/requisitesDemo';
import { parseRequisites } from './requisites';
import { programRuleLines, ruleLines } from './requisiteRules';

const expectedDirectory = resolve('src/fixtures/requisites/expected');
const expected = readdirSync(expectedDirectory).flatMap((file) => {
  const golden = JSON.parse(
    readFileSync(resolve(expectedDirectory, file), 'utf8'),
  ) as {
    scenarios: { visible: { kind: string; text?: string }[] }[];
  };
  return golden.scenarios.flatMap((s) =>
    s.visible.filter((v) => v.kind === 'text').map((v) => v.text),
  );
});
it('every parsed course and plan tree matches a frozen Python golden line block', () => {
  let rules = 0;
  let plans = 0;
  for (const fixture of requisitesFixtures) {
    const result = parseRequisites(fixture.body.course_requisites);
    if (result.kind !== 'ok') continue;
    for (const d of result.listing.documents)
      for (const s of Object.values(d.requisites)) {
        if (s.status === 'parsed') {
          expect(expected).toContain(ruleLines(s.rule).join('\n'));
          rules++;
        }
      }
    for (const c of result.listing.program_contexts)
      for (const p of c.plans) {
        expect(expected).toContain(programRuleLines(p.requirements).join('\n'));
        plans++;
      }
  }
  expect(rules).toBeGreaterThan(10);
  expect(plans).toBeGreaterThan(4);
});
export const leaf = (
  overrides: Partial<Extract<RequisiteNode, { kind: 'course' }>> = {},
): Extract<RequisiteNode, { kind: 'course' }> => ({
  kind: 'course',
  course_code: 'CS 5800',
  minimum_grade: null,
  academic_level: null,
  concurrent_allowed: false,
  children: [],
  ...overrides,
});
it('dedup is local identical leaves only; each leaf field and groups remain distinct', () => {
  const different = [
    leaf({ course_code: 'CS 7800' }),
    leaf({ minimum_grade: 'B' }),
    leaf({ academic_level: 'Graduate' }),
    leaf({ concurrent_allowed: true }),
  ];
  const inner: RequisiteNode = { kind: 'any_of', children: [leaf(), leaf()] };
  const root: RequisiteNode = {
    kind: 'all_of',
    children: [leaf(), leaf(), ...different, inner, inner],
  };
  const lines = ruleLines(root);
  expect(lines).toEqual([
    '- 全部分支（AND）（目录原文在这一组里把同一门课列了不止一次，这里只显示一次）',
    '  - CS 5800',
    '  - CS 7800',
    '  - CS 5800（最低成绩：B）',
    '  - CS 5800（原文 level 标记：Graduate（不自动判断适用学生））',
    '  - CS 5800（原文明示可并修；仍需核实其余条件）',
    '  - 任一分支（OR）（目录原文在这一组里把同一门课列了不止一次，这里只显示一次）',
    '    - CS 5800',
    '  - 任一分支（OR）（目录原文在这一组里把同一门课列了不止一次，这里只显示一次）',
    '    - CS 5800',
  ]);
});
const program = (overrides: Partial<ProgramNode>): ProgramNode => ({
  kind: 'condition',
  label: '条款',
  course_code: null,
  children: [],
  course_codes: [],
  subject_codes: [],
  course_ranges: [],
  excluded_course_codes: [],
  activate_when: null,
  min_courses: null,
  min_credits: null,
  min_areas: null,
  areas: {},
  ...overrides,
});
it('all seven program kinds preserve pools ranges exclusions area order and optional scope', () => {
  const node = program({
    kind: 'all_of',
    children: [
      program({
        kind: 'any_of',
        children: [
          program({ kind: 'course', course_code: 'CS 1' }),
          program({ kind: 'unmodeled' }),
        ],
      }),
      program({
        kind: 'optional',
        activate_when: '自选',
        children: [program({ kind: 'condition' })],
      }),
      program({
        kind: 'select',
        min_courses: 2,
        min_credits: 8,
        min_areas: 1,
        course_codes: ['CS 1', 'CS 2'],
        subject_codes: ['DS', 'CS'],
        course_ranges: [{ start: 'CS 5000', end: 'CS 5999' }],
        excluded_course_codes: ['CS 9'],
        areas: { Zebra: ['CS 2', 'CS 1'], Alpha: ['DS 1'] },
      }),
    ],
  });
  expect(programRuleLines(node)).toEqual([
    '- 全部分支（AND）：条款',
    '  - 任一分支（OR）：条款',
    '    - CS 1：条款',
    '    - 尚未建模：条款',
    '  - 可选分支：条款（自选；不是共同必修）',
    '    - 条件（需核实，未自动判定）：条款',
    '  - 组选：条款（至少 2 门；至少 8 学分；至少 1 个领域；不是所有候选均必修）',
    '    候选：CS 1、CS 2',
    '    科目前缀：DS、CS（仍需核实级别、先修与开课）',
    '    编号范围：CS 5000–CS 5999（不证明每个编号都有课程或当前开课）',
    '    排除：CS 9',
    '    领域 Zebra：CS 2、CS 1',
    '    领域 Alpha：DS 1',
  ]);
  expect(
    programRuleLines(
      program({ kind: 'select', min_courses: 0, min_credits: 0, min_areas: 0 }),
    ),
  ).toEqual(['- 组选：条款（；不是所有候选均必修）']);
});
