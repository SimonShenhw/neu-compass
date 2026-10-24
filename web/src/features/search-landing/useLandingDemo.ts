import { useEffect, useState } from 'react';
import type { Load } from '../../api/load';
import { fixtureLoad, landingSources } from '../../fixtures/landingDemo';
import type { LandingSpeed } from '../../fixtures/landingDemo';
import { parseProgramList } from '../../models/programs';
import { FEATURED_PROGRAM_IDS } from '../../models/landing';

export function useLandingDemo(scenario: string, speed: LandingSpeed) {
  const [state, setState] = useState<{
    programs: Load;
    curricula: Readonly<Record<string, Load>>;
    coop: Load;
  }>(() => ({
    programs: { status: 'loading' },
    curricula: {},
    coop: { status: 'loading' },
  }));
  // The caller keys each session by options/replay. No result belongs to a later session.
  useEffect(() => {
    if (speed === 'forever') return;
    const sources = landingSources(scenario);
    const multiplier = speed === 'instant' ? 0 : speed === 'slow' ? 4 : 1;
    let live = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const later = (ms: number, action: () => void) =>
      timers.push(
        setTimeout(() => {
          if (live) action();
        }, ms * multiplier),
      );
    later(300, () => {
      const programs = fixtureLoad(sources.programs);
      setState((s) => ({ ...s, programs }));
      const parsed =
        programs.status === 'ready' ? parseProgramList(programs.data) : null;
      if (parsed?.kind === 'ok')
        for (const id of FEATURED_PROGRAM_IDS) {
          if (!parsed.data.some((p) => p.program_id === id)) continue;
          later(300, () =>
            setState((s) => ({
              ...s,
              curricula: {
                ...s.curricula,
                [id]: fixtureLoad(sources.curricula[id]!),
              },
            })),
          );
        }
    });
    later(450, () =>
      setState((s) => ({ ...s, coop: fixtureLoad(sources.coop) })),
    );
    return () => {
      live = false;
      for (const timer of timers) clearTimeout(timer);
    };
  }, [scenario, speed]);
  return state;
}
