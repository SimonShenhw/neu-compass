import { CourseCode } from './CourseCode';
import styles from './RequisiteTree.module.css';

export type RequisiteNode =
  | { kind: 'course'; code: string; title: string; minimumGrade?: string }
  | { kind: 'any' | 'all'; children: readonly RequisiteNode[] };

export function RequisiteTree({
  node,
  onOpen,
}: {
  node: RequisiteNode;
  onOpen: (code: string) => void;
}) {
  if (node.kind === 'course')
    return (
      <button
        type="button"
        aria-label={`${node.code} ${node.title}${node.minimumGrade ? ` 最低 ${node.minimumGrade}` : ''}`}
        onClick={() => onOpen(node.code)}
        className={styles.leaf}
      >
        <CourseCode>{node.code}</CourseCode>
        <span>{node.title}</span>
        {node.minimumGrade && (
          <span className={styles.grade}>最低 {node.minimumGrade}</span>
        )}
      </button>
    );
  return (
    <div className={styles.tree}>
      <span className={styles.gate}>
        {node.kind === 'any' ? '满足其一' : '都要'}
      </span>
      <ul>
        {node.children.map((child, index) => (
          <li
            key={
              child.kind === 'course' ? child.code : `${child.kind}-${index}`
            }
          >
            <RequisiteTree node={child} onOpen={onOpen} />
          </li>
        ))}
      </ul>
    </div>
  );
}
