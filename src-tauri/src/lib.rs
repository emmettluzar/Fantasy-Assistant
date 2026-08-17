//! Fantasy Draft Assistant Tauri backend.
//!
//! Wires the Rust modules together:
//!
//! * [`sidecar`] - Python sidecar process management + monitoring.
//! * [`protocol`] - IPC message schema shared with Python and TypeScript.

mod protocol;
mod sidecar;

use sidecar::EngineState;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(EngineState::new())
        .invoke_handler(tauri::generate_handler![
            greet,
            sidecar::start_engine,
            sidecar::stop_engine,
            sidecar::engine_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}