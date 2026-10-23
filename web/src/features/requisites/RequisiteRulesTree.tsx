import type { RequisiteNode } from '../../api/requisites';
import { CourseCode } from '../../components/CourseCode';
import {
  groupChildren,
  groupTitle,
  leafSuffix,
} from '../../models/requisiteRules';
import styles from './Requisites.module.css';

export function RequisiteRulesTree({
  node,
  onOpenCourse,
}: {
  node: RequisiteNode;
  onOpenCourse: (code: string) => void;
}) {
  function item(value: RequisiteNode, depth: number, key = 0) {
    return (
      <li data-tree-depth={depth} key={key}>
        <div data-rule-line>
          {value.kind === 'course' ? (
            <>
              <button
                type="button"
                className={styles.courseButton}
                aria-label={`查看 ${value.course_code}`}
                onClick={() => onOpenCourse(value.course_code)}
              >
                <CourseCode>{value.course_code}</CourseCode>
              </button>
              {leafSuffix(value)}
            </>
          ) : (
            groupTitle(value)
          )}
        </div>
        {value.kind !== 'course' && (
          <ul>
            {groupChildren(value).map((child, index) =>
              item(child, depth + 1, index),
            )}
          </ul>
        )}
      </li>
    );
  }
  return <ul className={styles.tree}>{item(node, 0)}</ul>;
}
