import {
  useRef,
  useState,
  useEffect,
  useCallback,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  Subtitles,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SceneSegment {
  startTime: number;
  endTime: number;
  label?: string;
  color?: string;
}

interface VideoPlayerProps {
  src: string | null;
  poster?: string;
  scenes?: SceneSegment[];
  captionsUrl?: string;
  className?: string;
  onTimeUpdate?: (time: number) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// Pipeline step colors for scene segments
const SCENE_COLORS = [
  '#818CF8', // indigo
  '#F472B6', // pink
  '#34D399', // green
  '#FBBF24', // amber
  '#60A5FA', // blue
  '#A78BFA', // violet
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function VideoPlayer({
  src,
  poster,
  scenes = [],
  captionsUrl,
  className = '',
  onTimeUpdate,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);

  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [captionsOn, setCaptionsOn] = useState(true);
  const [showControls, setShowControls] = useState(true);
  const controlsTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // ---- Playback controls ----

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play();
      setPlaying(true);
    } else {
      video.pause();
      setPlaying(false);
    }
  }, []);

  const toggleMute = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setMuted(video.muted);
  }, []);

  const toggleCaptions = useCallback(() => {
    setCaptionsOn((prev) => !prev);
  }, []);

  const seek = useCallback((time: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(time, video.duration || 0));
  }, []);

  const toggleFullscreen = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void video.requestFullscreen();
    }
  }, []);

  // ---- Time updates ----

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      onTimeUpdate?.(video.currentTime);
    };
    const handleLoadedMetadata = () => {
      setDuration(video.duration);
    };
    const handleEnded = () => {
      setPlaying(false);
    };

    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('ended', handleEnded);

    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('ended', handleEnded);
    };
  }, [onTimeUpdate]);

  // ---- Keyboard shortcuts ----

  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault();
          togglePlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          seek(currentTime - 5);
          break;
        case 'ArrowRight':
          e.preventDefault();
          seek(currentTime + 5);
          break;
        case 'm':
          e.preventDefault();
          toggleMute();
          break;
        case 'f':
          e.preventDefault();
          toggleFullscreen();
          break;
        case 'c':
          e.preventDefault();
          toggleCaptions();
          break;
      }
    },
    [togglePlay, seek, currentTime, toggleMute, toggleFullscreen, toggleCaptions],
  );

  // ---- Scrubber click ----

  const handleScrubberClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const bar = progressRef.current;
      if (!bar || !duration) return;
      const rect = bar.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      seek(pct * duration);
    },
    [duration, seek],
  );

  // ---- Auto-hide controls ----

  const showControlsTemporarily = useCallback(() => {
    setShowControls(true);
    if (controlsTimerRef.current) clearTimeout(controlsTimerRef.current);
    controlsTimerRef.current = setTimeout(() => {
      if (playing) setShowControls(false);
    }, 3000);
  }, [playing]);

  useEffect(() => {
    return () => {
      if (controlsTimerRef.current) clearTimeout(controlsTimerRef.current);
    };
  }, []);

  // ---- Progress percentage ----
  const progressPct = duration > 0 ? (currentTime / duration) * 100 : 0;

  // ---- No source state ----
  if (!src) {
    return (
      <div
        className={`video-short-container flex items-center justify-center ${className}`}
      >
        <div className="text-center text-txt-tertiary">
          <Play size={48} className="mx-auto mb-2 opacity-30" />
          <p className="text-sm">No video available</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`video-short-container group ${className}`}
      onMouseMove={showControlsTemporarily}
      onMouseEnter={() => setShowControls(true)}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      // role="region" + aria-label is the WAI-ARIA-recommended container
      // for a media widget. role="application" hijacks every key from the
      // user's screen reader and isn't appropriate when our keys are just
      // play/pause/seek shortcuts on a regular HTML5 video.
      role="region"
      aria-label="Video player"
    >
      {/* Video Element */}
      <video
        ref={videoRef}
        src={src}
        poster={poster}
        className="absolute inset-0 w-full h-full object-contain bg-black"
        onClick={togglePlay}
        playsInline
        muted={muted}
      >
        {captionsUrl && captionsOn && (
          <track
            kind="subtitles"
            src={captionsUrl}
            srcLang="en"
            label="English"
            default
          />
        )}
      </video>

      {/* Play overlay (when paused) */}
      {!playing && (
        <div
          className="absolute inset-0 flex items-center justify-center bg-black/30 cursor-pointer"
          onClick={togglePlay}
        >
          <div className="w-14 h-14 rounded-full bg-accent/90 flex items-center justify-center shadow-accent-glow">
            <Play size={24} className="text-txt-onAccent ml-0.5" />
          </div>
        </div>
      )}

      {/* Controls overlay */}
      <div
        className={[
          'absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent',
          'transition-opacity duration-normal',
          showControls ? 'opacity-100' : 'opacity-0',
        ].join(' ')}
      >
        {/* Scrubber bar — exposed as an ARIA slider so screen readers
            announce the playback position and accept keyboard seek. */}
        <div
          ref={progressRef}
          className="relative h-1.5 bg-white/20 rounded-full cursor-pointer mb-2 group/scrubber"
          onClick={handleScrubberClick}
          role="slider"
          tabIndex={0}
          aria-label="Seek video"
          aria-valuemin={0}
          aria-valuemax={Math.max(0, Math.round(duration))}
          aria-valuenow={Math.round(currentTime)}
          aria-valuetext={`${Math.floor(currentTime / 60)}:${String(Math.floor(currentTime % 60)).padStart(2, '0')} of ${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}`}
        >
          {/* Scene segments */}
          {scenes.map((scene, i) => {
            if (!duration) return null;
            const left = (scene.startTime / duration) * 100;
            const width =
              ((scene.endTime - scene.startTime) / duration) * 100;
            return (
              <div
                key={i}
                className="absolute top-0 h-full rounded-full opacity-40"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  backgroundColor:
                    scene.color ?? SCENE_COLORS[i % SCENE_COLORS.length],
                }}
                title={scene.label ?? `Scene ${i + 1}`}
              />
            );
          })}

          {/* Progress fill */}
          <div
            className="absolute top-0 left-0 h-full bg-accent rounded-full"
            style={{ width: `${progressPct}%` }}
          />

          {/* Thumb */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-accent rounded-full shadow-accent-glow opacity-0 group-hover/scrubber:opacity-100 transition-opacity"
            style={{ left: `${progressPct}%`, marginLeft: '-6px' }}
          />
        </div>

        {/* Control buttons */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="text-white hover:text-accent transition-colors"
              aria-label={playing ? 'Pause' : 'Play'}
            >
              {playing ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <button
              onClick={toggleMute}
              className="text-white hover:text-accent transition-colors"
              aria-label={muted ? 'Unmute' : 'Mute'}
            >
              {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
            </button>
            <span className="text-xs text-white/70 font-mono tabular-nums">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {captionsUrl && (
              <button
                onClick={toggleCaptions}
                className={`transition-colors ${
                  captionsOn
                    ? 'text-accent'
                    : 'text-white/50 hover:text-white'
                }`}
                aria-label={captionsOn ? 'Hide captions' : 'Show captions'}
              >
                <Subtitles size={16} className={captionsOn ? '' : 'opacity-50'} />
              </button>
            )}
            <button
              onClick={toggleFullscreen}
              className="text-white hover:text-accent transition-colors"
              aria-label="Fullscreen"
            >
              <Maximize size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export { VideoPlayer };
export type { VideoPlayerProps, SceneSegment };
