import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { createQueryClient } from './api/queries';
import './styles/tokens.css';
import './styles/base.css';

const root = document.getElementById('root');
if (!root) throw new Error('Root element is missing');
const queryClient = createQueryClient();
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
