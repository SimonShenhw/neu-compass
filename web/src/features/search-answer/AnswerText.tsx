import { answerBlocks } from '../../models/answerText';
import type { Inline } from '../../models/answerText';
import styles from './SearchConversation.module.css';

function Inlines({ nodes }: { nodes: Inline[] }) {
  return nodes.map((node, index) => {
    if (node.t === 'text') return node.v;
    if (node.t === 'code') return <code key={index}>{node.v}</code>;
    if (node.t === 'strong')
      return (
        <strong key={index}>
          <Inlines nodes={node.c} />
        </strong>
      );
    return (
      <a key={index} href={node.href} target="_blank" rel="noopener noreferrer">
        {node.v}
      </a>
    );
  });
}
export function AnswerText({ text }: { text: string }) {
  return (
    <div data-kind="answer" className={styles.answer}>
      {answerBlocks(text).map((block, index) => {
        if (block.type === 'code')
          return (
            <pre key={index} data-answer-block="code">
              <code>{block.text}</code>
            </pre>
          );
        if (block.type === 'list') {
          const items = block.items.map((nodes, n) => (
            <li key={n}>
              <Inlines nodes={nodes} />
            </li>
          ));
          return block.ordered ? (
            <ol key={index} data-answer-block="list" start={block.start!}>
              {items}
            </ol>
          ) : (
            <ul key={index} data-answer-block="list">
              {items}
            </ul>
          );
        }
        return (
          <p
            key={index}
            data-answer-block={block.type}
            className={
              block.type === 'heading' ? styles.modelHeading : undefined
            }
          >
            <Inlines nodes={block.inlines} />
          </p>
        );
      })}
    </div>
  );
}
