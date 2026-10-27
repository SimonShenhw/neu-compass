// A course page's address (R1, R3e): /course/CS-6140, the code with each space as a hyphen, percent-encoded. The course
// page hands the path segment as it is to /resolve/course, which reads any separator and internal IDs too, so a link
// someone typed as /course/cs5800 still opens; codeFromPath only spells the segment back for display meanwhile.
import { collapseSpace } from './programFormat';

export function coursePath(code: string): string {
  return `/course/${encodeURIComponent(code.replaceAll(' ', '-'))}`;
}

export function codeFromPath(segment: string): string {
  return segment.replaceAll('-', ' ');
}

// The site shared links name, fixed at build time (src/api/apiBase.ts choosePublicBase; R0 16.4).
export const PUBLIC_BASE_URL: string = __PUBLIC_BASE_URL__;

export function courseShareUrl(code: string): string {
  return `${PUBLIC_BASE_URL}${coursePath(code)}`;
}

// What the address names, said back on the page: anyone can write the address, so it is shown on one line and cut to
// 64 characters, as Streamlit's _ref_label does (app/deep_links.py; it also drops backticks, there for Markdown). It
// drops every character that draws nothing as well, which Streamlit does not: format characters and the ones Unicode
// says to ignore (direction marks, zero-width spaces, soft hyphens, variation selectors, tags). Direction marks could
// turn the rest of the page's own sentence around (review A32).
const INVISIBLE = /[\p{Cf}\p{Default_Ignorable_Code_Point}]/gu;
export function refLabel(ref: string): string {
  return Array.from(
    collapseSpace(ref.replaceAll('`', '').replace(INVISIBLE, '')),
  )
    .slice(0, 64)
    .join('');
}
