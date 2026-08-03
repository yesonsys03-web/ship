#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::net::TcpStream;
use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct BackendState(Mutex<Option<CommandChild>>);

fn stop_backend(app: &tauri::AppHandle) {
    request_backend_shutdown(8770);
    let child = {
        let state = app.state::<BackendState>();
        let child = state.0.lock().expect("backend state lock failed").take();
        child
    };
    if let Some(child) = child {
        let _ = child.kill();
    }
}

fn request_backend_shutdown(port: u16) {
    if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
        let _ = stream
            .write_all(b"GET /shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            let (mut rx, child) = app
                .shell()
                .sidecar("ship-manager-backend")?
                .args(["--parent-pid".to_string(), std::process::id().to_string()])
                .spawn()?;
            *app.state::<BackendState>()
                .0
                .lock()
                .expect("backend state lock failed") = Some(child);

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("{}", String::from_utf8_lossy(&line))
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("{}", String::from_utf8_lossy(&line))
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build manager app")
        .run(|app_handle, event| match event {
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                stop_backend(app_handle)
            }
            _ => {}
        });
}
