import { useState, useCallback, useEffect, useRef } from "react";
import type { AccountUser } from "./lib/api";
import { checkHealth, fetchAccountMe, logoutAccount } from "./lib/api";
import { useWebcam } from "./hooks/useWebcam";
import { useSensing } from "./hooks/useSensing";
import { useTheme } from "./hooks/useTheme";
import { AccountNav } from "./components/AccountNav";
import { AccountChatPanel } from "./components/AccountChatPanel";
import { WebcamSensing } from "./components/WebcamSensing";
import { SensingStatus } from "./components/SensingStatus";
import { PictureBoard } from "./components/PictureBoard";
import { LandingPage } from "./components/LandingPage";
import { IconLogout, IconMoon, IconSun } from "./components/Icons";
import "./App.css";

function ThemeToggle({ className = "" }: { className?: string }) {
  const { isDark, toggleTheme } = useTheme();
  return (
    <button
      type="button"
      className={`theme-toggle ${className}`.trim()}
      onClick={toggleTheme}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? <IconSun size={18} /> : <IconMoon size={18} />}
    </button>
  );
}

function App() {
  const [accountUser, setAccountUser] = useState<AccountUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [webcamEnabled, setWebcamEnabled] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pictureBoardOpen, setPictureBoardOpen] = useState(true);
  const quickPhraseRef = useRef<((text: string) => Promise<void>) | null>(null);
  const healthPoll = useRef<ReturnType<typeof setInterval>>(undefined);

  const bindQuickPhrase = useCallback(
    (fn: ((text: string) => Promise<void>) | null) => {
      quickPhraseRef.current = fn;
    },
    [],
  );

  useEffect(() => {
    async function poll() {
      const ready = await checkHealth();
      if (ready) {
        setBackendReady(true);
        clearInterval(healthPoll.current);
      }
    }
    poll();
    healthPoll.current = setInterval(poll, 2000);
    return () => clearInterval(healthPoll.current);
  }, []);

  useEffect(() => {
    fetchAccountMe()
      .then(setAccountUser)
      .catch(() => setAccountUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [accountUser]);

  const {
    sensing,
    ready,
    initError,
    init,
    processFrame,
    resetCalibration,
  } = useSensing();

  const onFrame = useCallback(
    (video: HTMLVideoElement, timestamp: number) => {
      processFrame(video, timestamp);
    },
    [processFrame]
  );

  const { videoRef, active, error } = useWebcam({
    enabled: webcamEnabled && ready,
    onFrame,
  });

  async function handleWebcamToggle() {
    if (!webcamEnabled) {
      const ok = await init();
      if (ok) setWebcamEnabled(true);
    } else {
      setWebcamEnabled(false);
      resetCalibration();
    }
  }

  async function handleLogout() {
    await logoutAccount();
    setAccountUser(null);
  }

  if (!authChecked) {
    return (
      <div className="app-boot">
        <p>Loading…</p>
      </div>
    );
  }

  if (!accountUser) {
    return (
      <LandingPage
        themeToggle={<ThemeToggle />}
        backendReady={backendReady}
        onUserChange={setAccountUser}
      />
    );
  }

  return (
    <div className={`app-layout ${sidebarOpen ? "sidebar-open" : ""}`}>
      <button
        type="button"
        className="sidebar-toggle"
        aria-expanded={sidebarOpen}
        aria-controls="app-sidebar"
        onClick={() => setSidebarOpen((v) => !v)}
      >
        {sidebarOpen ? "Close menu" : "Menu"}
      </button>
      {sidebarOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Close menu"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside id="app-sidebar" className="sidebar">
        <div className="app-title-row">
          <h1 className="app-title">
            <img src="/favicon.svg" alt="" className="app-logo" />
            SPICA
          </h1>
          <div className="app-title-actions">
            <ThemeToggle />
            <button
              type="button"
              className="icon-text-btn"
              onClick={handleLogout}
              title="Log out"
            >
              <IconLogout size={16} />
              <span>Log out</span>
            </button>
          </div>
        </div>

        <AccountNav
          onUserChange={setAccountUser}
          pictureBoardOpen={pictureBoardOpen}
          onPictureBoardToggle={() => setPictureBoardOpen((v) => !v)}
        />

        <div className="sidebar-section">
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={webcamEnabled}
              onChange={handleWebcamToggle}
            />
            Enable webcam
          </label>
          <WebcamSensing videoRef={videoRef} active={active} error={error || initError} />
          {pictureBoardOpen && (
            <PictureBoard
              voice={accountUser.voice_preference}
              onPhraseSpoken={(text) => quickPhraseRef.current?.(text)}
            />
          )}
          <SensingStatus sensing={sensing} webcamActive={active} />
        </div>
      </aside>

      <main className="main-content">
        <AccountChatPanel
          user={accountUser}
          backendReady={backendReady}
          webcamEnabled={webcamEnabled && active}
          pictureBoardOpen={pictureBoardOpen}
          sensing={sensing}
          bindQuickPhrase={bindQuickPhrase}
        />
      </main>
    </div>
  );
}

export default App;
