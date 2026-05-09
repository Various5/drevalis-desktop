// Hide the console on Windows release builds. Dev builds keep stdout/stderr
// for debugging.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io;
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

/// Default API URL the webview loads when no SPA is bundled.
const DEFAULT_API_URL: &str = "http://localhost:8000";

/// How long we wait for the backend's TCP port to come up before showing
/// the window. The launcher needs to start uvicorn + arq + maybe Redis.
const BACKEND_READY_TIMEOUT: Duration = Duration::from_secs(20);

/// Holds a running backend `Child` so the OnExit hook can kill it cleanly.
struct BackendProcess(Mutex<Option<Child>>);

fn locate_backend_executable() -> Option<PathBuf> {
    // 1) Env override — explicit path wins over auto-discovery.
    if let Ok(p) = std::env::var("DREVALIS_BACKEND_PATH") {
        let path = PathBuf::from(p);
        if path.exists() {
            return Some(path);
        }
    }

    // 2) Sibling to the Tauri exe (production install layout).
    if let Ok(tauri_exe) = std::env::current_exe() {
        if let Some(dir) = tauri_exe.parent() {
            for candidate in [dir.join("drevalis.exe"), dir.join("backend").join("drevalis.exe")] {
                if candidate.exists() {
                    return Some(candidate);
                }
            }
        }
    }

    // 3) Development layout — `tauri dev` runs from tauri/src-tauri/, so
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

fn spawn_backend() -> io::Result<Option<Child>> {
    let Some(exe) = locate_backend_executable() else {
        eprintln!(
            "[drevalis-shell] backend not found. Set DREVALIS_BACKEND_PATH or run \
             scripts\\build\\win.ps1 to produce dist/drevalis/drevalis.exe."
        );
        return Ok(None);
    };
    println!("[drevalis-shell] spawning backend: {}", exe.display());

    // .arg("run") matches drevalis CLI; the launcher then spawns Redis +
    // worker + uvicorn. See src/drevalis/__main__.py.
    let child = Command::new(&exe).arg("run").spawn()?;
    Ok(Some(child))
}

fn kill_backend(state: &BackendProcess) {
    let mut guard = match state.0.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn main() {
    let context = tauri::generate_context!();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            // Spawn the backend before the window loads so the webview's
            // first request hits a live server. We don't fail the whole
            // app if the spawn errors — the user can still see the
            // helpful "backend not reachable" message inside the SPA.
            match spawn_backend() {
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

            Ok(())
        })
        .build(context)
        .expect("failed to build Tauri application");

    app.run(|app_handle: &AppHandle, event: RunEvent| {
        match event {
            // When the main window is closed, terminate the backend
            // before exiting. Without this the API + worker + Redis
            // continue running orphaned in the background.
            RunEvent::WindowEvent {
                event: WindowEvent::CloseRequested { .. },
                ..
            } => {
                kill_backend(&app_handle.state::<BackendProcess>());
            }
            // Belt-and-braces: also kill on full app exit (covers
            // tray-quit and shutdown signals).
            RunEvent::Exit => {
                kill_backend(&app_handle.state::<BackendProcess>());
            }
            _ => {}
        }
    });
}
