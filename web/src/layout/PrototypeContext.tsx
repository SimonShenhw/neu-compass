import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';
import { initialQuestion } from '../fixtures/courses';

type PrototypeState = {
  project: string;
  setProject: (project: string) => void;
  plan: string;
  setPlan: (plan: string) => void;
  question: string;
  hasSubmitted: boolean;
  submit: (question: string) => void;
  notice: string;
  announce: (message: string) => void;
};
const PrototypeContext = createContext<PrototypeState | null>(null);

export function PrototypeProvider({ children }: { children: ReactNode }) {
  const [project, setProjectValue] = useState('none');
  const [plan, setPlanValue] = useState('none');
  const [question, setQuestion] = useState(initialQuestion);
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const [notice, announce] = useState('');
  const setProject = (value: string) => {
    setProjectValue(value);
    setPlanValue('none');
  };
  const setPlan = (value: string) => {
    setPlanValue(value);
    // The only R1 search fixture plan belongs to MSCS.
    if (value !== 'none') setProjectValue('cs-ms');
  };
  const submit = (value: string) => {
    setQuestion(value);
    setHasSubmitted(true);
    announce('已更新演示问题；下面仍是固定示例回答，不生成或保存新回答。');
  };
  return (
    <PrototypeContext.Provider
      value={{
        project,
        setProject,
        plan,
        setPlan,
        question,
        hasSubmitted,
        submit,
        notice,
        announce,
      }}
    >
      {children}
    </PrototypeContext.Provider>
  );
}

export function usePrototype() {
  const value = useContext(PrototypeContext);
  if (!value) throw new Error('PrototypeProvider is required');
  return value;
}
