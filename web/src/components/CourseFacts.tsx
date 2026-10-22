import { Info } from 'lucide-react';
import { Chips } from './Chips';
import { CourseCode } from './CourseCode';
import { BAD_CELL, courseHeader, detailCell } from '../models/compare';
import type { DetailRow, JsonObject } from '../models/compare';
import styles from './CourseFacts.module.css';

export function CourseHeaderFacts({ body }: { body: JsonObject }) {
  const header = courseHeader(body);
  if (!header) return <p>{BAD_CELL}</p>;
  return (
    <div className={styles.header}>
      <CourseCode>{header.identity.primary_code}</CourseCode>
      <strong>{header.identity.primary_name}</strong>
      {header.metadata.length > 0 && (
        <div className={styles.metadata}>
          {header.metadata.map((item) => (
            <span key={item.label}>
              {item.label} {item.value}
            </span>
          ))}
        </div>
      )}
      {header.notice && (
        <p className={styles.notice}>
          <Info aria-hidden="true" />
          {header.notice}
        </p>
      )}
      {header.creditRange && (
        <p className={styles.note}>{header.creditRange}</p>
      )}
    </div>
  );
}
export function CourseFactCell({
  row,
  body,
}: {
  row: DetailRow;
  body: JsonObject;
}) {
  const cell = detailCell(row, body);
  return (
    <div className={styles.cell}>
      {cell.topics && cell.topics.length > 0 && <Chips items={cell.topics} />}
      {cell.programs?.map((p, index) => (
        <div className={styles.placement} key={index}>
          <strong>{p.name}</strong>
          <span>{p.label}</span>
          {p.semester && <span>{p.semester}</span>}
        </div>
      ))}
      {cell.lines.map((line, index) => (
        <p
          data-kind={line.kind}
          key={index}
          className={line.kind === 'note' ? styles.note : styles.main}
        >
          {line.notice && <Info aria-hidden="true" />}
          {line.catalogUrl ? (
            <>
              课程描述来自 <a href={line.catalogUrl}>NEU 官方课程目录</a>{' '}
              的存档副本，不是实时核对。
            </>
          ) : (
            line.text
          )}
        </p>
      ))}
    </div>
  );
}
