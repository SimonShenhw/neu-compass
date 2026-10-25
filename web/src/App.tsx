import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppShell } from './layout/AppShell';
import { PrototypeProvider } from './layout/PrototypeContext';
import { SearchPage } from './pages/SearchPage';
import { CourseDetail } from './pages/CourseDetail';
import { CompareRoute } from './pages/CompareRoute';
import { CompareDemoPage } from './pages/CompareDemoPage';
import { ProgramsPage } from './pages/ProgramsPage';
import { CoopRoute } from './pages/CoopRoute';
import { CoopDemoPage } from './pages/CoopDemoPage';
import { PrivacyRoute } from './pages/PrivacyRoute';
import { PrivacyDemoPage } from './pages/PrivacyDemoPage';
import { RequisitesDemoPage } from './pages/RequisitesDemoPage';
import { CourseDetailDemoPage } from './pages/CourseDetailDemoPage';
import { NotFound } from './pages/NotFound';

const SearchDemoPage = lazy(() => import('./pages/SearchDemoPage'));

export function App() {
  return (
    <PrototypeProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<SearchPage />} />
          <Route path="/course/:code" element={<CourseDetail />} />
          <Route path="/compare" element={<CompareRoute />} />
          <Route path="/programs" element={<ProgramsPage />} />
          <Route path="/coop" element={<CoopRoute />} />
          <Route path="/privacy" element={<PrivacyRoute />} />
          <Route path="/compare-demo" element={<CompareDemoPage />} />
          <Route path="/coop-demo" element={<CoopDemoPage />} />
          <Route path="/privacy-demo" element={<PrivacyDemoPage />} />
          <Route path="/requisites-demo" element={<RequisitesDemoPage />} />
          <Route
            path="/search-demo"
            element={
              <Suspense fallback={<p role="status">正在加载搜索演示…</p>}>
                <SearchDemoPage />
              </Suspense>
            }
          />
          <Route
            path="/course-detail-demo"
            element={<CourseDetailDemoPage />}
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </PrototypeProvider>
  );
}
