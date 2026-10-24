import { useEffect, useState } from 'react';
import type { Load } from '../../api/load';
import { programLoad } from '../../fixtures/programsDemo';

// The owning keyed demo node recreates this hook when the source/speed/replay changes.
export function useProgramDemoLoad(
  name: string | null,
  speed: string,
): Load | null {
  const [result, setResult] = useState<Load | null>(() =>
    name ? { status: 'loading' } : null,
  );
  useEffect(() => {
    if (!name || speed === 'forever') return;
    let active = true;
    const timer = setTimeout(
      () => {
        if (active) setResult(programLoad(name));
      },
      speed === 'instant' ? 0 : speed === 'slow' ? 1200 : 300,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [name, speed]);
  return result;
}
