import type { ChatEvent, ChatFailure } from '../api/chat';
import { parseChatMeta } from './chatMeta';
import type { ParsedMeta } from './chatMeta';

export interface Turn {
  id: number;
  question: string;
  allowSave: boolean;
  status: 'waiting' | 'answering' | 'done' | 'stopped' | 'failed';
  meta: ParsedMeta | null;
  text: string;
  error: { errorType: string; message: string } | null;
  failure: ChatFailure | null;
  receipt: unknown;
}
export function newTurn(
  id: number,
  question: string,
  allowSave: boolean,
): Turn {
  return {
    id,
    question,
    allowSave,
    status: 'waiting',
    meta: null,
    text: '',
    error: null,
    failure: null,
    receipt: null,
  };
}
export const isRunning = (turn: Turn) =>
  turn.status === 'waiting' || turn.status === 'answering';
export function turnReducer(turn: Turn, event: ChatEvent): Turn {
  if (turn.status === 'waiting' && event.type === 'meta')
    return { ...turn, status: 'answering', meta: parseChatMeta(event.meta) };
  if (turn.status !== 'answering') return turn;
  if (event.type === 'token') return { ...turn, text: turn.text + event.text };
  if (event.type === 'error')
    return {
      ...turn,
      status: 'stopped',
      error: { errorType: event.errorType, message: event.message },
    };
  if (event.type === 'done')
    return { ...turn, status: 'done', receipt: event.feedback };
  return turn;
}
export const INCOMPLETE = '回答流未完整结束；仅保留部分内容，请稍后手动重试。';
export function incompleteTurn(turn: Turn): Turn {
  return {
    ...turn,
    status: 'stopped',
    error: { errorType: 'incomplete_stream', message: INCOMPLETE },
  };
}
