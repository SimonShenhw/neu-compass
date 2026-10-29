// The shell's <main> (AppShell): where focus goes when the page changes, when the skip link is used, and when nothing
// nearer is left of what a page replaced (R6).
export const MAIN_CONTENT = 'main-content';

export function focusMainContent(options?: FocusOptions) {
  document.getElementById(MAIN_CONTENT)?.focus(options);
}
