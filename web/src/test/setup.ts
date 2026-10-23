import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, vi } from 'vitest';
import { clearCompare } from '../models/compareList';
import { resetCompareDemoForTests } from '../fixtures/compareDemo';

// jsdom has no layout or pointer-capture implementation. Keep real Radix behavior.
if (!Element.prototype.scrollIntoView)
  Element.prototype.scrollIntoView = () => {};
if (!Element.prototype.hasPointerCapture)
  Element.prototype.hasPointerCapture = () => false;
if (!Element.prototype.setPointerCapture)
  Element.prototype.setPointerCapture = () => {};
if (!Element.prototype.releasePointerCapture)
  Element.prototype.releasePointerCapture = () => {};
if (!window.PointerEvent) vi.stubGlobal('PointerEvent', MouseEvent);
if (!window.ResizeObserver)
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
// Canvas/contrast cannot be checked in jsdom; null denotes an unsupported context.
// DOM axe tests explicitly disable only color-contrast. Token contrast is tested separately.
HTMLCanvasElement.prototype.getContext = () => null;
window.scrollTo = () => {};

const blockedFetch = vi.fn(() => {
  throw new Error('R1 must not make network requests');
});
beforeEach(() => {
  blockedFetch.mockClear();
  vi.stubGlobal('fetch', blockedFetch);
});
afterEach(() => {
  cleanup();
  clearCompare();
  resetCompareDemoForTests();
  expect(blockedFetch).not.toHaveBeenCalled();
});
