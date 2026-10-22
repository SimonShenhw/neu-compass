import { Route, Routes } from 'react-router-dom';
import { AppShell } from './layout/AppShell';
import { PrototypeProvider } from './layout/PrototypeContext';
import { SearchPage } from './pages/SearchPage';
import { CourseDetail } from './pages/CourseDetail';
import { ComparePage } from './pages/ComparePage';
import { ProgramsPage } from './pages/ProgramsPage';
import { CoopPage } from './pages/CoopPage';
import { PrivacyPage } from './pages/PrivacyPage';
import { NotFound } from './pages/NotFound';

export function App() {
  return (
    <PrototypeProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<SearchPage />} />
          <Route path="/course/:code" element={<CourseDetail />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/programs" element={<ProgramsPage />} />
          <Route path="/coop" element={<CoopPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </PrototypeProvider>
  );
}
