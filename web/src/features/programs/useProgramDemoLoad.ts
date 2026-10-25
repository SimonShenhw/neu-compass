import { useEffect, useState } from 'react';
import type { Load } from '../../api/load';
import { programLoad } from '../../fixtures/programsDemo';

const LOADING: Load = { status: 'loading' };

// Only a result read for exactly this name, speed and request shows; until one arrives this gives loading. The demo
// counts its request numbers up whenever it reads again, so a restarted read never shows an earlier result and the
// component showing it is not recreated (and keeps its focus).
export function useProgramDemoLoad(
  name: string | null,
  speed: string,
  request = 0,
): Load | null {
  const key = JSON.stringify([name, speed, request]);
  const [read, setRead] = useState<{ key: string; result: Load } | null>(null);
  useEffect(() => {
    if (!name || speed === 'forever') return;
    let active = true;
    const timer = setTimeout(
      () => {
        if (active) setRead({ key, result: programLoad(name) });
      },
      speed === 'instant' ? 0 : speed === 'slow' ? 1200 : 300,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key, name, speed]);
  if (!name) return null;
  return read?.key === key ? read.result : LOADING;
}
