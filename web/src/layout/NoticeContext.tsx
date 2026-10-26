// The shell's one-line announcements (R1; since R3e the only part of the prototype's state that is left): what came
// back from Google, which AppShell shows at the top of the page, and the offline demo shell's note under its page. What
// a login or logout pressed in the account box came to is the box's own (useSession's note).
import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';

export interface Notices {
  notice: string;
  announce: (message: string) => void;
}

const NoticeContext = createContext<Notices | null>(null);

export function NoticeProvider({ children }: { children: ReactNode }) {
  const [notice, announce] = useState('');
  return (
    <NoticeContext.Provider value={{ notice, announce }}>
      {children}
    </NoticeContext.Provider>
  );
}

export function useNotice(): Notices {
  const value = useContext(NoticeContext);
  if (!value) throw new Error('NoticeProvider is required');
  return value;
}
