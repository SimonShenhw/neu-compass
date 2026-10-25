import { useEffect, useState } from 'react';
import type { Load } from '../../api/load';
import { programLoad } from '../../fixtures/programsDemo';

const LOADING: Load = { status: 'loading' };

// A new name, speed or request starts the read again. Until it arrives this gives loading, never an earlier read's
// result, so the demo restarts a read without recreating (and unfocusing) the component that shows it.
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
