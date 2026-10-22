import { Route, Routes } from 'react-router-dom';
import { AppShell } from './layout/AppShell';
import { PrototypeProvider } from './layout/PrototypeContext';
import { SearchPage } from './pages/SearchPage';
import { CourseDetail } from './pages/CourseDetail';
import { CompareDemoPage } from './pages/CompareDemoPage';
import { ProgramsPage } from './pages/ProgramsPage';
import { CoopDemoPage } from './pages/CoopDemoPage';
import { PrivacyPage } from './pages/PrivacyPage';
import { NotFound } from './pages/NotFound';

export function App() {
  return (
    <PrototypeProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<SearchPage />} />
          <Route path="/course/:code" element={<CourseDetail />} />
          <Route path="/compare" element={<CompareDemoPage />} />
          <Route path="/programs" element={<ProgramsPage />} />
          <Route path="/coop" element={<CoopDemoPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </PrototypeProvider>
  );
}
