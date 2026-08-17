//! Python sidecar process management for the Fantasy Draft Assistant.
//!
//! The Rust backend owns the lifecycle of the local analytics engine: it
//! spawns the isolated virtual environment's Python interpreter running
//! `src-python/server.py` (the WebSocket IPC server), monitors it, and
//! restarts it automatically with exponential backoff if it crashes.
//!
//! The frontend never manages the process directly; it calls the Tauri
//! commands exposed here (`start_engine`, `stop_engine`, `engine_status`) and
//! then talks to the engine over `ws://127.0.0.1:8080`.

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::mpsc::Receiver;

use crate::protocol::{DEFAULT_HOST, DEFAULT_PORT, DEFAULT_WS_URL};

/// How long to wait for a TCP health probe to `ws://127.0.0.1:8080`.
const HEALTH_TIMEOUT: Duration = Duration::from_millis(300);

/// Initial backoff between restart attempts.
const RESTART_BASE: Duration = Duration::from_secs(1);

/// Ceiling on restart backoff.
const RESTART_MAX: Duration = Duration::from_secs(10);

/// Status payload returned to the frontend and emitted as an event.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineStatus {
    pub running: bool,
    pub healthy: bool,
    pub pid: Option<u32>,
    pub ws_url: String,
}

/// Shared, interior-mutability state for the managed engine process.
pub struct EngineInner {
    /// When true the monitor loop keeps the engine alive (auto-restart).
    restart: AtomicBool,
    /// Live child handle, used to kill the process from `stop_engine`.
    child: Mutex<Option<CommandChild>>,
    /// Last known OS process id.
    pid: Mutex<Option<u32>>,
}

impl Default for EngineInner {
    fn default() -> Self {
        Self {
            restart: AtomicBool::new(false),
            child: Mutex::new(None),
            pid: Mutex::new(None),
        }
    }
}

/// Tauri-managed state for the engine process.
#[derive(Clone, Default)]
pub struct EngineState {
    pub inner: Arc<EngineInner>,
}

impl EngineState {
    pub fn new() -> Self {
        Self::default()
    }
}

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

/// Resolve the pair `(python_executable, server_script)`.
///
/// Development uses `CARGO_MANIFEST_DIR/../src-python`; production uses the
/// bundled resource directory (`bundle.resources` copies `src-python`).
fn resolve_engine_paths(app: &AppHandle) -> Result<(PathBuf, PathBuf), String> {
    #[cfg(target_os = "windows")]
    let python_rel: &str = "venv/Scripts/python.exe";
    #[cfg(not(target_os = "windows"))]
    let python_rel: &str = "venv/bin/python";

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(dev_root) = manifest_dir.parent() {
        let dev_python = dev_root.join("src-python").join(python_rel);
        let dev_script = dev_root.join("src-python").join("server.py");
        if dev_python.exists() && dev_script.exists() {
            return Ok((dev_python, dev_script));
        }
    }

    let res_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("resource dir unavailable: {e}"))?;
    let prod_python = res_dir.join("src-python").join(python_rel);
    let prod_script = res_dir.join("src-python").join("server.py");
    Ok((prod_python, prod_script))
}

// ---------------------------------------------------------------------------
// Spawning
// ---------------------------------------------------------------------------

fn spawn_child(app: &AppHandle) -> Result<(Receiver<CommandEvent>, CommandChild), String> {
    let (python, script) = resolve_engine_paths(app)?;
    let script_dir = script
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));

    let cmd = app.shell().command(python.to_string_lossy().to_string());
    cmd.args([
        script.to_string_lossy().to_string(),
        "--host".to_string(),
        DEFAULT_HOST.to_string(),
        "--port".to_string(),
        DEFAULT_PORT.to_string(),
        "--log-level".to_string(),
        "INFO".to_string(),
    ])
    .current_dir(script_dir)
    .env("PYTHONUNBUFFERED", "1")
    .spawn()
    .map_err(|e| format!("spawn failed: {e}"))
}

// ---------------------------------------------------------------------------
// Monitor loop
// ---------------------------------------------------------------------------

/// Drive the command output stream until the process terminates or errors.
async fn drive_until_exit(mut rx: Receiver<CommandEvent>) {
    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                match String::from_utf8(bytes) {
                    Ok(text) if !text.trim().is_empty() => {
                        eprintln!("[engine] {}", text.trim());
                    }
                    _ => {}
                }
            }
            CommandEvent::Terminated(payload) => {
                eprintln!("[engine] exited: {payload:?}");
                break;
            }
            CommandEvent::Error(err) => {
                eprintln!("[engine] error: {err}");
                break;
            }
            _ => {}
        }
    }
}

/// The single ownership loop for the engine process.
///
/// While `restart` is set it keeps spawning the engine; when the child exits
/// it waits a bounded backoff and restarts. Setting `restart` to false ends
/// the loop and releases the process handle.
async fn engine_loop(app: AppHandle, inner: Arc<EngineInner>) {
    let mut backoff = RESTART_BASE;

    while inner.restart.load(Ordering::SeqCst) {
        match spawn_child(&app) {
            Ok((rx, child)) => {
                let pid = child.pid();
                if let Ok(mut guard) = inner.child.lock() {
                    *guard = Some(child);
                }
                if let Ok(mut guard) = inner.pid.lock() {
                    *guard = Some(pid);
                }
                emit_status(&app, &inner, "started");
                backoff = RESTART_BASE;

                drive_until_exit(rx).await;

                if let Ok(mut guard) = inner.child.lock() {
                    *guard = None;
                }
                if let Ok(mut guard) = inner.pid.lock() {
                    *guard = None;
                }
                emit_status(&app, &inner, "stopped");
            }
            Err(err) => {
                eprintln!("[engine] spawn failed: {err}");
            }
        }

        if !inner.restart.load(Ordering::SeqCst) {
            break;
        }
        tokio::time::sleep(backoff).await;
        backoff = (backoff * 2).min(RESTART_MAX);
    }

    emit_status(&app, &inner, "exited");
}

fn emit_status(app: &AppHandle, inner: &EngineInner, event: &str) {
    let pid = inner.pid.lock().ok().and_then(|g| *g);
    let status = EngineStatus {
        running: inner.restart.load(Ordering::SeqCst),
        healthy: check_health(DEFAULT_HOST, DEFAULT_PORT),
        pid,
        ws_url: DEFAULT_WS_URL.to_string(),
    };
    let _ = app.emit("engine-status", status);
    eprintln!("[engine] event={event} pid={:?}", pid);
}

// ---------------------------------------------------------------------------
// Health probe
// ---------------------------------------------------------------------------

/// Cheap TCP reachability probe against the WebSocket server port.
pub fn check_health(host: &str, port: u16) -> bool {
    let addr: SocketAddr = match format!("{host}:{port}").parse() {
        Ok(addr) => addr,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&addr, HEALTH_TIMEOUT).is_ok()
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

/// Start the engine (idempotent) and return its current status.
#[tauri::command]
pub async fn start_engine(app: AppHandle, state: State<'_, EngineState>) -> Result<EngineStatus, String> {
    let inner = state.inner.clone();

    // `swap` returns the previous value. If it was already true, the monitor
    // loop is already running and we must not spawn a second one.
    let already_running = inner.restart.swap(true, Ordering::SeqCst);
    if !already_running {
        tauri::async_runtime::spawn(engine_loop(app.clone(), inner.clone()));
    }

    Ok(snapshot_status(&inner))
}

/// Stop the engine (idempotent) and return its current status.
#[tauri::command]
pub async fn stop_engine(state: State<'_, EngineState>) -> Result<EngineStatus, String> {
    let inner = state.inner.clone();

    inner.restart.store(false, Ordering::SeqCst);
    if let Ok(mut guard) = inner.child.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }
    if let Ok(mut guard) = inner.pid.lock() {
        *guard = None;
    }

    Ok(snapshot_status(&inner))
}

/// Report the current engine process status and WebSocket health.
#[tauri::command]
pub fn engine_status(state: State<'_, EngineState>) -> Result<EngineStatus, String> {
    Ok(snapshot_status(&state.inner))
}

fn snapshot_status(inner: &EngineInner) -> EngineStatus {
    let pid = inner.pid.lock().ok().and_then(|g| *g);
    EngineStatus {
        running: inner.restart.load(Ordering::SeqCst),
        healthy: check_health(DEFAULT_HOST, DEFAULT_PORT),
        pid,
        ws_url: DEFAULT_WS_URL.to_string(),
    }
}