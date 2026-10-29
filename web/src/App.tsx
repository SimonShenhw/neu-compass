import { Route, Routes } from 'react-router-dom';
import { offlineDemoRoutes, shellDemoRoutes } from './demoRoutes';
import { AppShell } from './layout/AppShell';
import { SearchRoute } from './pages/SearchRoute';
import { CourseRoute } from './pages/CourseRoute';
import { CompareRoute } from './pages/CompareRoute';
import { ProgramRoute, ProgramsRoute } from './pages/ProgramsRoute';
import { CoopRoute } from './pages/CoopRoute';
import { PrivacyRoute } from './pages/PrivacyRoute';
import { NotFound } from './pages/NotFound';

export function App() {
  return (
    <Routes>
      {offlineDemoRoutes}
      <Route element={<AppShell />}>
        <Route path="/" element={<SearchRoute />} />
        <Route path="/course/:code" element={<CourseRoute />} />
        <Route path="/compare" element={<CompareRoute />} />
        <Route path="/programs" element={<ProgramsRoute />} />
        <Route path="/programs/:programId" element={<ProgramRoute />} />
        <Route path="/coop" element={<CoopRoute />} />
        <Route path="/privacy" element={<PrivacyRoute />} />
        {shellDemoRoutes}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
