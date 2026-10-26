import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppShell } from './layout/AppShell';
import { NoticeProvider } from './layout/NoticeContext';
import { SearchRoute } from './pages/SearchRoute';
import { CourseRoute } from './pages/CourseRoute';
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
const ProgramsDemoPage = lazy(() => import('./pages/ProgramsDemoPage'));
const OfflineDemoShell = lazy(() => import('./features/demo/OfflineDemoShell'));
const SearchLandingDemoPage = lazy(
  () => import('./pages/SearchLandingDemoPage'),
);

export function App() {
  return (
    <NoticeProvider>
      <Routes>
        <Route
          element={
            <Suspense fallback={<p role="status">正在加载演示…</p>}>
              <OfflineDemoShell />
            </Suspense>
          }
        >
          <Route
            path="/programs-demo"
            element={
              <Suspense fallback={<p role="status">正在加载培养方案演示…</p>}>
                <ProgramsDemoPage />
              </Suspense>
            }
          />
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
          <Route path="/" element={<SearchRoute />} />
          <Route path="/course/:code" element={<CourseRoute />} />
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
    </NoticeProvider>
  );
}
