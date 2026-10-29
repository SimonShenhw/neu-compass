import { lazy, Suspense } from 'react';
import { Route } from 'react-router-dom';
import { CompareDemoPage } from './pages/CompareDemoPage';
import { CoopDemoPage } from './pages/CoopDemoPage';
import { PrivacyDemoPage } from './pages/PrivacyDemoPage';
import { RequisitesDemoPage } from './pages/RequisitesDemoPage';
import { CourseDetailDemoPage } from './pages/CourseDetailDemoPage';

// The demo pages R1–R5 built for acceptance, on synthetic data: on the dev server and in the tests only. Every build
// gets demoRoutes.none.tsx in this module's place (vite.config.ts), so no demo page, nor its data or styles, reaches a
// bundle students are served (R6).
const SearchDemoPage = lazy(() => import('./pages/SearchDemoPage'));
const ProgramsDemoPage = lazy(() => import('./pages/ProgramsDemoPage'));
const PlanDraftDemoPage = lazy(() => import('./pages/PlanDraftDemoPage'));
const OfflineDemoShell = lazy(() => import('./features/demo/OfflineDemoShell'));
const SearchLandingDemoPage = lazy(
  () => import('./pages/SearchLandingDemoPage'),
);

// Demos in a shell of their own, which asks the API nothing.
export const offlineDemoRoutes = (
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
      path="/programs-draft-demo"
      element={
        <Suspense fallback={<p role="status">正在加载选课草案演示…</p>}>
          <PlanDraftDemoPage />
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
);

// Demos inside the real shell.
export const shellDemoRoutes = (
  <>
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
    <Route path="/course-detail-demo" element={<CourseDetailDemoPage />} />
  </>
);
