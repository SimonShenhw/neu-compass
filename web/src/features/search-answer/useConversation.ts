import { useCallback, useEffect, useRef, useState } from 'react';
import type { AskOptions } from '../../api/chat';
import { isChatFailure, UNKNOWN_FAILURE } from '../../models/chatFailure';
import {
  incompleteTurn,
  isRunning,
  newTurn,
  turnReducer,
} from '../../models/chatTurn';
import type { Turn } from '../../models/chatTurn';

export function useConversation() {
  const [turns, setTurns] = useState<readonly Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const owner = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const nextId = useRef(1);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      owner.current?.abort();
      owner.current = null;
    };
  }, []);
  const ask = useCallback(({ question, allowSave, source }: AskOptions) => {
    if (!mounted.current || owner.current !== null) return;
    const controller = new AbortController();
    owner.current = controller;
    let current = newTurn(nextId.current++, question, allowSave);
    const initial = current;
    setTurns((previous) => [...previous, initial]);
    setBusy(true);
    const active = () =>
      mounted.current &&
      owner.current === controller &&
      !controller.signal.aborted;
    const update = () => {
      const snapshot = current;
      if (active())
        setTurns((previous) =>
          previous.map((turn) => (turn.id === snapshot.id ? snapshot : turn)),
        );
    };
    void (async () => {
      let received = false;
      try {
        for await (const event of source(controller.signal)) {
          if (!active()) return;
          received = true;
          current = turnReducer(current, event);
          update();
          if (!isRunning(current)) break;
        }
        if (active() && isRunning(current)) {
          current = incompleteTurn(current);
          update();
        }
      } catch (failure) {
        if (!active()) return;
        current = received
          ? incompleteTurn(current)
          : {
              ...current,
              status: 'failed',
              failure: isChatFailure(failure) ? failure : UNKNOWN_FAILURE,
            };
        update();
      } finally {
        if (owner.current === controller) {
          owner.current = null;
          if (mounted.current) setBusy(false);
        }
      }
    })();
  }, []);
  return { turns, busy, ask };
}
