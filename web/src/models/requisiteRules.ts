import type {
  ProgramNode,
  ProgramPlan,
  RequisiteNode,
} from '../api/requisites';

export function leafSuffix(node: Extract<RequisiteNode, { kind: 'course' }>) {
  const details: string[] = [];
  if (node.minimum_grade) details.push(`最低成绩：${node.minimum_grade}`);
  if (node.academic_level)
    details.push(
      `原文 level 标记：${node.academic_level}（不自动判断适用学生）`,
    );
  if (node.concurrent_allowed) details.push('原文明示可并修；仍需核实其余条件');
  return details.length ? `（${details.join('；')}）` : '';
}
export function groupChildren(
  node: Exclude<RequisiteNode, { kind: 'course' }>,
) {
  const seen = new Set<string>();
  return node.children.filter((child) => {
    if (child.kind !== 'course') return true;
    const key = JSON.stringify([
      child.kind,
      child.course_code,
      child.minimum_grade,
      child.academic_level,
      child.concurrent_allowed,
    ]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
export function groupTitle(node: Exclude<RequisiteNode, { kind: 'course' }>) {
  const operator =
    node.kind === 'all_of' ? '全部分支（AND）' : '任一分支（OR）';
  return (
    operator +
    (groupChildren(node).length < node.children.length
      ? '（目录原文在这一组里把同一门课列了不止一次，这里只显示一次）'
      : '')
  );
}
export function ruleLines(node: RequisiteNode, depth = 0): string[] {
  const prefix = `${'  '.repeat(depth)}- `;
  if (node.kind === 'course')
    return [prefix + node.course_code + leafSuffix(node)];
  return [
    prefix + groupTitle(node),
    ...groupChildren(node).flatMap((child) => ruleLines(child, depth + 1)),
  ];
}
export function programRuleLines(node: ProgramNode, depth = 0): string[] {
  const indent = '  '.repeat(depth);
  if (node.kind === 'course')
    return [`${indent}- ${node.course_code}：${node.label}`];
  if (node.kind === 'condition' || node.kind === 'unmodeled')
    return [
      `${indent}- ${node.kind === 'condition' ? '条件（需核实，未自动判定）' : '尚未建模'}：${node.label}`,
    ];
  if (node.kind === 'select') {
    const minima: string[] = [];
    if (node.min_courses) minima.push(`至少 ${node.min_courses} 门`);
    if (node.min_credits) minima.push(`至少 ${node.min_credits} 学分`);
    if (node.min_areas) minima.push(`至少 ${node.min_areas} 个领域`);
    const lines = [
      `${indent}- 组选：${node.label}（${minima.join('；')}；不是所有候选均必修）`,
    ];
    if (node.course_codes.length)
      lines.push(`${indent}  候选：${node.course_codes.join('、')}`);
    if (node.subject_codes.length)
      lines.push(
        `${indent}  科目前缀：${node.subject_codes.join('、')}（仍需核实级别、先修与开课）`,
      );
    for (const range of node.course_ranges)
      lines.push(
        `${indent}  编号范围：${range.start}–${range.end}（不证明每个编号都有课程或当前开课）`,
      );
    if (node.excluded_course_codes.length)
      lines.push(`${indent}  排除：${node.excluded_course_codes.join('、')}`);
    for (const [name, codes] of Object.entries(node.areas))
      lines.push(`${indent}  领域 ${name}：${codes.join('、')}`);
    return lines;
  }
  if (node.kind === 'optional')
    return [
      `${indent}- 可选分支：${node.label}（${node.activate_when}；不是共同必修）`,
      ...programRuleLines(node.children[0]!, depth + 1),
    ];
  const operator =
    node.kind === 'all_of' ? '全部分支（AND）' : '任一分支（OR）';
  return [
    `${indent}- ${operator}：${node.label}`,
    ...node.children.flatMap((child) => programRuleLines(child, depth + 1)),
  ];
}
export function planLabel(plan: ProgramPlan) {
  const path = { standard: '普通 MS', align: 'Align', bridge: 'Bridge' }[
    plan.pathway
  ];
  return `${plan.program_id} · ${plan.campus} · Catalog ${plan.catalog_year} · ${path} · ${plan.concentration ?? '共同部分／未限定 concentration'}`;
}
