// Hide the console on Windows release builds. Dev builds keep stdout/stderr
// for debugging.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io;
use std::net::TcpStream;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

/// Windows ``CREATE_NO_WINDOW`` process-creation flag. The PyInstaller
/// bundle is a console-subsystem app, so a vanilla ``Command::spawn``
/// pops a black cmd-style window alongside the Tauri webview. Users
/// regularly close that window thinking it's a stray terminal, which
/// kills the backend and breaks the app. This flag suppresses the
/// console window for the spawned process tree; the launcher's Python
/// side mirrors it for its own subprocess.Popen calls.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

/// How long we wait for the backend's TCP port to come up before showing
/// the window. The launcher needs to start uvicorn + arq + maybe Redis.
const BACKEND_READY_TIMEOUT: Duration = Duration::from_secs(20);

/// Holds a running backend `Child` so the OnExit hook can kill it cleanly.
struct BackendProcess(Mutex<Option<Child>>);

fn locate_backend_executable(app: &tauri::AppHandle) -> Option<PathBuf> {
    // 1) Env override — explicit path wins over auto-discovery.
    if let Ok(p) = std::env::var("DREVALIS_BACKEND_PATH") {
        let path = PathBuf::from(p);
        if path.exists() {
            return Some(path);
        }
    }

    // 2) Tauri resource_dir — production install layout. ``bundle.resources``
    // in tauri.conf.json maps dist/drevalis/* into ``backend/`` under
    // resource_dir(). On NSIS this resolves to <install_dir>/resources/
    // backend/drevalis.exe alongside _internal/.
    if let Ok(resource_dir) = app.path().resource_dir() {
        let candidate = resource_dir.join("backend").join("drevalis.exe");
        if candidate.exists() {
            return Some(candidate);
        }
    }

    // 3) Sibling to the Tauri exe (alternate production layout, kept for
    // when the bundle isn't using bundle.resources).
    if let Ok(tauri_exe) = std::env::current_exe() {
        if let Some(dir) = tauri_exe.parent() {
            for candidate in [dir.join("drevalis.exe"), dir.join("backend").join("drevalis.exe")] {
                if candidate.exists() {
                    return Some(candidate);
                }
            }
        }
    }

    // 4) Development layout — `tauri dev` runs from tauri/src-tauri/, so
    // `../../dist/drevalis/drevalis.exe` is the bundle produced by
    // scripts/build/win.ps1.
    if let Ok(cwd) = std::env::current_dir() {
        let dev_path = cwd
            .ancestors()
            .nth(2)
            .map(|root| root.join("dist").join("drevalis").join("drevalis.exe"));
        if let Some(p) = dev_path {
            if p.exists() {
                return Some(p);
            }
        }
    }

    None
}

fn wait_for_port(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect_timeout(
            &format!("{}:{}", host, port).parse().unwrap(),
            Duration::from_millis(200),
        )
        .is_ok()
        {
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}

fn spawn_backend(app: &tauri::AppHandle) -> io::Result<Option<Child>> {
    let Some(exe) = locate_backend_executable(app) else {
        eprintln!(
            "[drevalis-shell] backend not found. Set DREVALIS_BACKEND_PATH or run \
             scripts\\build\\win.ps1 to produce dist/drevalis/drevalis.exe."
        );
        return Ok(None);
    };
    println!("[drevalis-shell] spawning backend: {}", exe.display());

    // .arg("run") matches drevalis CLI; the launcher then spawns Redis +
    // worker + uvicorn. See src/drevalis/__main__.py.
    let mut cmd = Command::new(&exe);
    cmd.arg("run");
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let child = cmd.spawn()?;
    Ok(Some(child))
}

fn kill_backend(state: &BackendProcess) {
    let mut guard = match state.0.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    let Some(mut child) = guard.take() else {
        return;
    };

    // On Windows, `child.kill()` calls `TerminateProcess` which kills only
    // the immediate child (`drevalis.exe`). The Python launcher's
    // grandchildren — `redis-server.exe`, the arq worker, and uvicorn —
    // survive and keep file handles open on `_internal/_asyncio.pyd` and
    // `resources/bin/win/redis-server.exe`. NSIS auto-updates then bomb
    // out with "Error opening file for writing".
    //
    // Tree-kill via `taskkill /F /T /PID <pid>` so the whole subtree dies
    // before this function returns. `/T` walks the descendant tree, `/F`
    // forces termination on each. We still call `child.kill()` afterwards
    // as a fallback for non-Windows builds and as a cleanup if taskkill
    // raced our child exiting.
    #[cfg(windows)]
    {
        let pid = child.id();
        let _ = Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }

    let _ = child.kill();
    let _ = child.wait();
}

/// Initialise crash telemetry for the Tauri shell process.
///
/// DSN is read at compile time via ``option_env!`` so CI release
/// builds bake in the production Glitchtip DSN while local dev builds
/// stay quiet. Returns the ``ClientInitGuard`` which must be kept
/// alive for the duration of the program — Sentry flushes pending
/// events on drop, so binding to a top-level `let _guard = ...` is
/// required (an `_` binding drops immediately and skips the flush).
fn init_telemetry() -> Option<sentry::ClientInitGuard> {
    let dsn = option_env!("DREVALIS_TELEMETRY_DSN")?;
    if dsn.is_empty() {
        return None;
    }
    let release = option_env!("CARGO_PKG_VERSION").map(|v| v.to_string());
    let environment = option_env!("DREVALIS_ENVIRONMENT")
        .unwrap_or("alpha")
        .to_string();
    Some(sentry::init((
        dsn,
        sentry::ClientOptions {
            release: release.map(Into::into),
            environment: Some(environment.into()),
            // Hard PII off — desktop user is the data subject; the
            // Python backend SDK uses the same posture.
            send_default_pii: false,
            // Capture native panics. Default panic-hook integration
            // is wired by the ``panic`` feature in Cargo.toml.
            attach_stacktrace: true,
            ..Default::default()
        },
    )))
}

fn main() {
    // Bind the guard at top-level main scope so it lives until program
    // exit; Sentry's flush-on-drop only runs while the guard is held.
    let _telemetry_guard = init_telemetry();

    let context = tauri::generate_context!();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            // Spawn the backend before the window loads so the webview's
            // first request hits a live server. We don't fail the whole
            // app if the spawn errors — the user can still see the
            // helpful "backend not reachable" message inside the SPA.
            match spawn_backend(&app.handle().clone()) {
                Ok(Some(child)) => {
                    let state = app.state::<BackendProcess>();
                    *state.0.lock().unwrap() = Some(child);
                }
                Ok(None) => {
                    eprintln!("[drevalis-shell] continuing without backend spawn");
                }
                Err(err) => {
                    eprintln!("[drevalis-shell] backend spawn failed: {err}");
                }
            }

            // Wait for the API port to come up so the webview doesn't show
            // a connection-refused page on cold boot.
            let ready = wait_for_port("127.0.0.1", 8000, BACKEND_READY_TIMEOUT);
            if !ready {
                eprintln!(
                    "[drevalis-shell] backend didn't open :8000 within {:?}; loading window anyway",
                    BACKEND_READY_TIMEOUT
                );
            }

            // Production: navigate the webview to the FastAPI server so
            // the SPA's relative XHRs (``/api/v1/...``) hit the same
            // origin. Tauri's default in release loads frontendDist via
            // ``tauri://`` -- a separate origin from the API, which
            // breaks fetches. In debug builds we leave Tauri's devUrl
            // (Vite dev server on :3000) in place; Vite proxies API
            // calls to :8000 and gives us HMR for free.
            #[cfg(not(debug_assertions))]
            {
                if let Some(win) = app.get_webview_window("main") {
                    let target = "http://127.0.0.1:8000/".parse().unwrap();
                    if let Err(err) = win.navigate(target) {
                        eprintln!("[drevalis-shell] navigate failed: {err}");
                    }
                } else {
                    eprintln!("[drevalis-shell] main window not found");
                }
            }

            // ── Tray icon ────────────────────────────────────────────
            // Window close hides to tray (BRIEF GOTCHAS: don't kill the
            // worker mid-generation). Tray "Quit" is the only way to
            // actually exit -- which then triggers RunEvent::Exit and
            // the backend cleanup.
            let open_item = MenuItem::with_id(
                app,
                "tray_open",
                "Open Drevalis",
                true,
                None::<&str>,
            )?;
            let quit_item = MenuItem::with_id(
                app,
                "tray_quit",
                "Quit",
                true,
                None::<&str>,
            )?;
            let menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            let _tray = TrayIconBuilder::with_id("main")
                .tooltip("Drevalis Creator Studio")
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "tray_open" => {
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.unminimize();
                            let _ = win.set_focus();
                        }
                    }
                    "tray_quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Left-click on the tray icon also re-opens the window;
                    // matches the Windows convention.
                    if let tauri::tray::TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        if let Some(win) = tray.app_handle().get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.unminimize();
                            let _ = win.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .build(context)
        .expect("failed to build Tauri application");

    app.run(|app_handle: &AppHandle, event: RunEvent| {
        match event {
            // The main window's close button hides to tray instead of
            // exiting -- preserves any active generation per BRIEF
            // GOTCHAS ("must not kill the worker on a UI close-window
            // event"). The user re-opens via tray-icon click or "Open
            // Drevalis" menu, or quits explicitly via tray "Quit".
            RunEvent::WindowEvent {
                label,
                event: WindowEvent::CloseRequested { api, .. },
                ..
            } if label == "main" => {
                if let Some(win) = app_handle.get_webview_window(&label) {
                    let _ = win.hide();
                }
                api.prevent_close();
            }
            // Real exit (tray "Quit", system shutdown) takes the backend
            // tree down with it.
            RunEvent::Exit => {
                kill_backend(&app_handle.state::<BackendProcess>());
            }
            _ => {}
        }
    });
}
