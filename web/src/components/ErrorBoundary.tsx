import { Component } from 'react';
import type { ReactNode } from 'react';
import { Button } from './Button';
import { EmptyState } from './EmptyState';

// What a page that failed to draw says: one plain sentence and a way to start over, never the error itself (R0 14.12,
// R6).
export const PAGE_FAILED = '这一页出了问题，没能显示出来。';
export const APP_FAILED = '页面出了问题，没能显示出来。';
// Reloading, as an object the tests can watch.
export const pageReload = { reload: () => window.location.reload() };

// Catches what the pages under it throw while drawing. In the shell (`where` is the address shown) the sidebar and
// the top bar stay, and going to another address tries again, without drawing the pages anew while nothing failed.
// At the top (`where` is null) nothing else could be drawn. The error's own text is never shown.
export class ErrorBoundary extends Component<
  { children: ReactNode; where: string | null },
  { failed: boolean }
> {
  override state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  override componentDidUpdate(previous: { where: string | null }) {
    if (this.state.failed && previous.where !== this.props.where)
      this.setState({ failed: false });
  }
  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert">
        <EmptyState
          action={<Button onClick={() => pageReload.reload()}>重新加载</Button>}
        >
          {this.props.where === null ? APP_FAILED : PAGE_FAILED}
        </EmptyState>
      </div>
    );
  }
}
