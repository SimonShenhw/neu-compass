import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { ProgramList } from './ProgramList';
import { ProgramCurriculum } from './ProgramCurriculum';
import {
  curriculumProps,
  edit,
  goldens,
  readProgramDom,
  renderGolden,
} from './programTestUtils';
import { programScenarios } from '../../fixtures/programsScenarios';
import { PROGRAM_INTRO, PLAN_PLACEHOLDER } from '../../models/programFormat';

describe('program page actual DOM reference', () => {
  it.each(goldens)(
    '$name matches every visible item, nesting, option, action and URL',
    async (g) => {
      expect(programScenarios[g.name as keyof typeof programScenarios]).toEqual(
        g.props,
      );
      const { container } = renderGolden(g);
      expect(await readProgramDom(container)).toEqual(g.visible);
    },
  );
});
it('loading and failed policy reads never hide the selected plan rules', () => {
  const props = curriculumProps();
  const { rerender } = render(
    <ProgramCurriculum {...props} policies={{ status: 'loading' }} />,
  );
  expect(screen.getByText('正在加载政策证据…')).toBeInTheDocument();
  expect(document.querySelector('pre')).not.toBeNull();
  rerender(
    <ProgramCurriculum
      {...props}
      policies={{
        status: 'failed',
        failure: {
          status: 503,
          errorType: null,
          retryAfter: null,
          invalidFields: [],
          reason: null,
        },
      }}
    />,
  );
  expect(
    screen.getByText(
      '无法加载所选方案的政策证据；未使用旧缓存，方案规则仍可浏览。',
    ),
  ).toBeInTheDocument();
  expect(document.querySelector('pre')).not.toBeNull();
});
it.each([undefined, 'x', 'A'.repeat(64)])(
  'missing or invalid revision %s refuses evidence and shares only the project',
  (revision) => {
    const props = curriculumProps();
    props.planRevisions = revision ? { [props.selectedPlanId!]: revision } : {};
    const { container } = render(<ProgramCurriculum {...props} />);
    expect(
      screen.getByText(
        '政策响应与当前所选方案的范围／内容版本不一致；请刷新方案后重试，未显示旧证据。',
      ),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-kind="share_url"]'),
    ).toHaveTextContent(/^https:\/\/compass.example.test\/\?program=cs-ms$/);
    expect(screen.queryByText('官方政策来源')).not.toBeInTheDocument();
  },
);
it('select is controlled, can clear, and never silently chooses the sole plan', async () => {
  const props = curriculumProps('ds-plan-selected');
  props.selectedPlanId = null;
  const { rerender } = render(<ProgramCurriculum {...props} />);
  expect(screen.getByRole('combobox')).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(props.onSelectPlan).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('combobox'));
  const options = await screen.findAllByRole('option');
  await userEvent.click(options[1]!);
  expect(props.onSelectPlan).toHaveBeenCalledWith(
    'ds-ms-boston-2026-2027-standard-ai',
  );
  expect(screen.getByRole('combobox')).toHaveTextContent(PLAN_PLACEHOLDER);
  props.selectedPlanId = 'ds-ms-boston-2026-2027-standard-ai';
  rerender(<ProgramCurriculum {...props} />);
  await userEvent.click(screen.getByRole('combobox'));
  await userEvent.click(
    await screen.findByRole('option', { name: PLAN_PLACEHOLDER }),
  );
  expect(props.onSelectPlan).toHaveBeenLastCalledWith(null);
  props.selectedPlanId = 'gone';
  rerender(<ProgramCurriculum {...props} />);
  expect(screen.getByRole('combobox')).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(document.querySelector('pre')).toBeNull();
  expect(props.onSelectPlan).toHaveBeenCalledTimes(2);
});
it('all buttons call only their intended callback with the literal ID', () => {
  const props = curriculumProps();
  render(<ProgramCurriculum {...props} />);
  fireEvent.click(screen.getByRole('button', { name: '所有培养方案' }));
  fireEvent.click(screen.getByRole('button', { name: '刷新方案及政策证据' }));
  fireEvent.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  expect(props.onBack).toHaveBeenCalledExactlyOnceWith();
  expect(props.onRefresh).toHaveBeenCalledExactlyOnceWith();
  expect(props.onViewCourse).toHaveBeenCalledExactlyOnceWith('c-cs-5010');
  expect(props.onSelectPlan).not.toHaveBeenCalled();
  cleanup();
  const open = vi.fn(),
    retry = vi.fn();
  const { rerender } = render(
    <ProgramList
      programs={{
        status: 'ready',
        data: [
          {
            program_id: 'literal-id',
            prefix: 'P',
            full_name: 'Name',
            course_count: 1,
            plan_count: 0,
          },
        ],
      }}
      onOpenProgram={open}
      onRetry={retry}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '查看 P 的课程表' }));
  expect(open).toHaveBeenCalledExactlyOnceWith('literal-id');
  rerender(
    <ProgramList
      programs={{
        status: 'failed',
        failure: {
          status: 503,
          errorType: null,
          retryAfter: null,
          invalidFields: [],
          reason: null,
        },
      }}
      onOpenProgram={open}
      onRetry={retry}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(retry).toHaveBeenCalledExactlyOnceWith();
});
it('data is literal text, preserves spaces and only checked official URLs become anchors', () => {
  const props = curriculumProps();
  const text =
    '<b>x</b> [链接](https://example.com) javascript:alert(1)\n  next';
  if (props.curriculum.status !== 'ready' || props.policies?.status !== 'ready')
    throw new Error('fixtures');
  for (const path of [
    'prefix',
    'full_name',
    'notes',
    'plans.2.notes',
    'plans.2.source_excerpt',
    'plans.2.requirements.label',
    'plans.2.concentration',
    'semesters.0.courses.0.primary_name',
    'semesters.0.courses.0.notes',
  ])
    edit(props.curriculum.data, path, text);
  edit(props.policies.data, 'scope.concentration', text);
  edit(props.policies.data, 'link.concentration', text);
  for (const path of [
    'policies.0.fragments.0.summary',
    'policies.0.fragments.0.source_paragraph',
  ])
    edit(props.policies.data, path, text);
  const { container } = render(<ProgramCurriculum {...props} />);
  expect(container.querySelector('b,script,img')).toBeNull();
  expect(container.querySelector('pre')).toHaveTextContent('<b>x</b>');
  expect(
    container.textContent!.split('javascript:alert(1)').length,
  ).toBeGreaterThan(9);
  expect(
    container.querySelector('[data-kind="share_url"]')?.textContent,
  ).toContain('concentration=%22%3Cb%3Ex');
  for (const link of container.querySelectorAll('a')) {
    expect(['官方目录来源', '官方政策来源']).toContain(link.textContent);
    expect(link.href).toMatch(/^https:\/\/catalog\.northeastern\.edu\//);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
  expect(container.querySelector('pre')!.textContent).toContain('\n  next');
});
it.each(['list', 'cs-standard-ready', 'cs-text-edge', 'cs-404', 'loading'])(
  '%s has no axe violations with all disclosures expanded',
  async (name) => {
    const rendered =
      name === 'loading'
        ? render(
            <ProgramList
              programs={{ status: 'loading' }}
              onOpenProgram={vi.fn()}
              onRetry={vi.fn()}
            />,
          )
        : renderGolden(goldens.find((g) => g.name === name)!);
    for (const d of rendered.container.querySelectorAll('details'))
      d.open = true;
    expect(screen.getByText(PROGRAM_INTRO)).toBeInTheDocument();
    expect(
      (
        await axe(rendered.container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  },
);
