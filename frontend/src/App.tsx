import { lazy, Suspense, useEffect, useState } from 'react';
import { Routes, Route, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from '@/components/layout/Layout';
import { EditorLayout } from '@/components/layout/EditorLayout';
import { LicenseGate } from '@/components/LicenseGate';
import { LoginGate } from '@/components/LoginGate';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { ToastProvider } from '@/components/ui/Toast';
import { TooltipProvider } from '@/components/ui/Tooltip';
import { ThemeProvider } from '@/lib/theme';
import { ProgressProvider } from '@/lib/progress-context';
import { AuthProvider } from '@/lib/AuthContext';
import { Spinner } from '@/components/ui/Spinner';
import NotFound from '@/pages/NotFound';

// ---------------------------------------------------------------------------
// Lazy-loaded pages (code splitting)
// ---------------------------------------------------------------------------

const Dashboard = lazy(() => import('@/pages/dashboard'));
const SeriesList = lazy(() => import('@/pages/SeriesList'));
const SeriesDetail = lazy(() => import('@/pages/SeriesDetail'));
const EpisodesList = lazy(() => import('@/pages/EpisodesList'));
const EpisodeDetail = lazy(() => import('@/pages/EpisodeDetail'));
const Audiobooks = lazy(() => import('@/pages/Audiobooks'));
const AudiobookDetail = lazy(() => import('@/pages/AudiobookDetail'));
const Calendar = lazy(() => import('@/pages/Calendar'));
const Logs = lazy(() => import('@/pages/Logs'));
const Jobs = lazy(() => import('@/pages/Jobs'));
const Settings = lazy(() => import('@/pages/Settings'));
const Help = lazy(() => import('@/pages/Help'));
const YouTube = lazy(() => import('@/pages/YouTube'));
const Usage = lazy(() => import('@/pages/Usage'));
const CloudGPU = lazy(() => import('@/pages/CloudGPU'));
const Assets = lazy(() => import('@/pages/Assets'));
const EpisodeEditor = lazy(() => import('@/pages/EpisodeEditor'));
const AudiobookEditor = lazy(() => import('@/pages/AudiobookEditor'));
const ShotList = lazy(() => import('@/pages/ShotList'));
const Login = lazy(() => import('@/pages/Login'));
const ResetPassword = lazy(() => import('@/pages/ResetPassword'));
const SocialPlatform = lazy(() => import('@/pages/SocialPlatform'));
const CharacterPacks = lazy(() => import('@/pages/CharacterPacks'));

// ---------------------------------------------------------------------------
// Loading fallback
// ---------------------------------------------------------------------------

function PageLoadingFallback() {
  return (
    <div className="flex items-center justify-center h-[60vh]">
      <Spinner size="lg" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// YouTube OAuth Callback (not lazy — tiny component)
// ---------------------------------------------------------------------------

function YouTubeCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    navigate('/settings', { replace: true });
  }, [navigate]);

  return (
    <div className="flex items-center justify-center h-[60vh]">
      <p className="text-sm text-txt-secondary">
        Connecting YouTube... Redirecting to settings.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// React Query client (Phase 3.1)
// ---------------------------------------------------------------------------
//
// Resource lists (episodes, series, jobs history, settings, license,
// health) flow through React Query for snapshot + invalidation +
// refetch-on-focus. The WebSocket via ``useActiveJobsProgress()`` keeps
// owning *in-flight* job state — Query layer doesn't replace WS-driven
// progress (R6 boundary).
//
// staleTime 30s — the dashboard and list pages all want "looks fresh
// when I come back" without firing a request on every render.
// refetchOnWindowFocus true — coming back from a tab that was open
// for hours should re-validate.

function App() {
  // Client lives in component state so HMR doesn't recreate it on every
  // module reload (recreating wipes the cache + cancels every in-flight
  // request, which is jarring during dev).
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: true,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
    <ThemeProvider>
    <ToastProvider>
    <TooltipProvider delayDuration={300}>
    <AuthProvider>
    <ProgressProvider>
    <LicenseGate>
    <ErrorBoundary>
    <Suspense fallback={<PageLoadingFallback />}>
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Public reset-password page — no LoginGate or LicenseGate. */}
      <Route path="/reset-password" element={<ResetPassword />} />
      {/* Fullscreen editor — no sidebar / header so the timeline has
          the whole viewport. */}
      <Route
        element={
          <LoginGate>
            <EditorLayout />
          </LoginGate>
        }
      >
        <Route path="/episodes/:episodeId/edit" element={<EpisodeEditor />} />
        <Route path="/audiobooks/:audiobookId/edit" element={<AudiobookEditor />} />
      </Route>
      <Route
        element={
          <LoginGate>
            <Layout />
          </LoginGate>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/series" element={<SeriesList />} />
        <Route path="/series/:seriesId" element={<SeriesDetail />} />
        <Route path="/episodes" element={<EpisodesList />} />
        <Route path="/episodes/:episodeId" element={<EpisodeDetail />} />
        <Route path="/episodes/:episodeId/shot-list" element={<ShotList />} />
        <Route path="/audiobooks" element={<Audiobooks />} />
        <Route path="/audiobooks/:audiobookId" element={<AudiobookDetail />} />
        <Route path="/calendar" element={<Calendar />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/help" element={<Help />} />
        <Route path="/youtube" element={<YouTube />} />
        <Route path="/social/:platform" element={<SocialPlatform />} />
        <Route path="/usage" element={<Usage />} />
        <Route path="/cloud-gpu" element={<CloudGPU />} />
        <Route path="/assets" element={<Assets />} />
        <Route path="/character-packs" element={<CharacterPacks />} />
        <Route path="/youtube/callback" element={<YouTubeCallback />} />
        {/* Catch-all 404 — renders inside Layout so the chrome stays. */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
    </Suspense>
    </ErrorBoundary>
    </LicenseGate>
    </ProgressProvider>
    </AuthProvider>
    </TooltipProvider>
    </ToastProvider>
    </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
