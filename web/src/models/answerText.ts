export type Inline =
  | { t: 'text'; v: string }
  | { t: 'code'; v: string }
  | { t: 'strong'; c: Inline[] }
  | { t: 'link'; v: string; href: string };
export type AnswerBlock =
  | { type: 'paragraph' | 'heading'; inlines: Inline[] }
  | { type: 'list'; ordered: boolean; start: number | null; items: Inline[][] }
  | { type: 'code'; text: string };

const URL = String.raw`https://catalog\.northeastern\.edu/course-descriptions/[a-z]{2,8}/(?:#[A-Za-z0-9_-]{1,64})?`;
const markdownLink = new RegExp(
  String.raw`\[([^\[\]\n]{1,200})\]\([ \t]{0,20}<?(${URL})>?(?:[ \t]{1,20}"[^"\n]{0,200}")?[ \t]{0,20}\)`,
  'gu',
);
const autolink = new RegExp(`<(${URL})>`, 'gu');
const bareLink = new RegExp(URL, 'gu');
const code = /`([^`\n]+)`/gu;
const strong = /\*\*([^ \t\n*](?:[^*\n]*[^ \t\n*])?)\*\*/gu;
const fencePattern = /^ {0,3}(`{3,}|~{3,})(.*)$/u;
const plain = (v: string): Inline[] => (v ? [{ t: 'text', v }] : []);
function merge(nodes: Inline[]): Inline[] {
  const out: Inline[] = [];
  for (const node of nodes) {
    const previous = out.at(-1);
    if (previous?.t === 'text' && node.t === 'text') previous.v += node.v;
    else out.push(node);
  }
  return out;
}
function split(
  text: string,
  pattern: RegExp,
  make: (m: RegExpMatchArray) => Inline,
  rest: (text: string) => Inline[],
): Inline[] {
  const nodes: Inline[] = [];
  let at = 0;
  for (const match of text.matchAll(pattern)) {
    nodes.push(...rest(text.slice(at, match.index)), make(match));
    at = match.index + match[0].length;
  }
  nodes.push(...rest(text.slice(at)));
  return nodes;
}
function links(text: string): Inline[] {
  const bare = (part: string) =>
    split(part, bareLink, (m) => ({ t: 'link', v: m[0], href: m[0] }), plain);
  const auto = (part: string) =>
    split(part, autolink, (m) => ({ t: 'link', v: m[1]!, href: m[1]! }), bare);
  return split(
    text,
    markdownLink,
    (m) => ({ t: 'link', v: m[1]!, href: m[2]! }),
    auto,
  );
}
export function answerInlines(text: string): Inline[] {
  const bold = (part: string) =>
    split(
      part,
      strong,
      (m) => ({ t: 'strong', c: merge(links(m[1]!)) }),
      links,
    );
  return merge(split(text, code, (m) => ({ t: 'code', v: m[1]! }), bold));
}
export function answerBlocks(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] | null = null;
  let listing: {
    ordered: boolean;
    start: number | null;
    items: string[][];
  } | null = null;
  let fence: { marker: string; lines: string[] } | null = null;
  function flush() {
    if (paragraph)
      blocks.push({
        type: 'paragraph',
        inlines: answerInlines(paragraph.join('\n')),
      });
    if (listing)
      blocks.push({
        type: 'list',
        ordered: listing.ordered,
        start: listing.start,
        items: listing.items.map((lines) => answerInlines(lines.join('\n'))),
      });
    paragraph = null;
    listing = null;
  }
  const trim = (s: string) => s.replace(/^[ \t]+|[ \t]+$/gu, '');
  for (const line of text
    .replaceAll('\r\n', '\n')
    .replaceAll('\r', '\n')
    .split('\n')) {
    if (fence) {
      const close = fencePattern.exec(line);
      if (
        close &&
        trim(close[2]!) === '' &&
        close[1]![0] === fence.marker[0] &&
        close[1]!.length >= fence.marker.length
      ) {
        blocks.push({ type: 'code', text: fence.lines.join('\n') });
        fence = null;
      } else fence.lines.push(line);
      continue;
    }
    const opening = fencePattern.exec(line);
    if (opening) {
      flush();
      fence = { marker: opening[1]!, lines: [] };
      continue;
    }
    if (/^[ \t]*$/u.test(line)) {
      flush();
      continue;
    }
    const heading = /^ {0,3}#{1,6}[ \t]+(.*?)[ \t]*$/u.exec(line);
    if (heading?.[1]) {
      flush();
      blocks.push({ type: 'heading', inlines: answerInlines(heading[1]) });
      continue;
    }
    const bullet = /^[ \t]*[-*+][ \t]+(.*)$/u.exec(line);
    const numbered = /^[ \t]*(\d{1,9})[.)][ \t]+(.*)$/u.exec(line);
    if (bullet || numbered) {
      const ordered = numbered !== null;
      if (paragraph || (listing && listing.ordered !== ordered)) flush();
      listing ??= {
        ordered,
        start: numbered ? Number(numbered[1]) : null,
        items: [],
      };
      listing.items.push([trim(numbered ? numbered[2]! : bullet![1]!)]);
    } else if (listing) listing.items.at(-1)!.push(trim(line));
    else {
      paragraph ??= [];
      paragraph.push(trim(line));
    }
  }
  if (fence) blocks.push({ type: 'code', text: fence.lines.join('\n') });
  flush();
  return blocks;
}
