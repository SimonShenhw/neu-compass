import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppShell } from './layout/AppShell';
import { PrototypeProvider } from './layout/PrototypeContext';
import { SearchPage } from './pages/SearchPage';
import { CourseDetail } from './pages/CourseDetail';
import { CompareDemoPage } from './pages/CompareDemoPage';
import { ProgramsPage } from './pages/ProgramsPage';
import { CoopDemoPage } from './pages/CoopDemoPage';
import { PrivacyDemoPage } from './pages/PrivacyDemoPage';
import { RequisitesDemoPage } from './pages/RequisitesDemoPage';
import { CourseDetailDemoPage } from './pages/CourseDetailDemoPage';
import { NotFound } from './pages/NotFound';

const SearchDemoPage = lazy(() => import('./pages/SearchDemoPage'));
const OfflineDemoShell = lazy(() => import('./features/demo/OfflineDemoShell'));
const SearchLandingDemoPage = lazy(
  () => import('./pages/SearchLandingDemoPage'),
);

export function App() {
  return (
    <PrototypeProvider>
      <Routes>
        <Route
          element={
            <Suspense fallback={<p role="status">正在加载落地演示…</p>}>
              <OfflineDemoShell />
            </Suspense>
          }
        >
          <Route
            path="/search-landing-demo"
            element={
              <Suspense fallback={<p role="status">正在加载落地演示…</p>}>
                <SearchLandingDemoPage />
              </Suspense>
            }
          />
        </Route>
        <Route element={<AppShell />}>
          <Route path="/" element={<SearchPage />} />
          <Route path="/course/:code" element={<CourseDetail />} />
          <Route path="/compare" element={<CompareDemoPage />} />
          <Route path="/programs" element={<ProgramsPage />} />
          <Route path="/coop" element={<CoopDemoPage />} />
          <Route path="/privacy" element={<PrivacyDemoPage />} />
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
