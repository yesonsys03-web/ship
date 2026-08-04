#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::collections::VecDeque;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_READY_PATH: &str = "/ready";
const LEGACY_DEV_BACKEND_PORT: u16 = 8765;
const LOG_TAIL_LIMIT: usize = 12;
const HEALTH_POLL_ATTEMPTS: usize = 100;
const HEALTH_POLL_DELAY: Duration = Duration::from_millis(120);
const CONNECT_TIMEOUT: Duration = Duration::from_millis(900);
const HEALTH_HTTP_TIMEOUT: Duration = Duration::from_millis(900);
const HISTORY_HTTP_TIMEOUT: Duration = Duration::from_secs(2);
const MUTATION_HTTP_TIMEOUT: Duration = Duration::from_secs(120);
const WINDOWS_SHIP_DB_DIR: &str = "//Mserver/USA_DB/test_jn/ship_db";

static BACKEND_STARTUP_LOCK: Mutex<()> = Mutex::new(());

struct BackendState(Mutex<BackendProcess>);

#[derive(Default)]
struct BackendProcess {
    child: Option<CommandChild>,
    port: Option<u16>,
    generation: u64,
    stdout: VecDeque<String>,
    stderr: VecDeque<String>,
    termination: Option<String>,
    spawn_error: Option<String>,
}

#[tauri::command(async)]
fn sender_health(app: tauri::AppHandle) -> Result<Value, String> {
    let port = ensure_backend(&app)?;
    proxy_json(port, "GET", "/health", None, HEALTH_HTTP_TIMEOUT)
}

#[tauri::command(async)]
fn sender_history(app: tauri::AppHandle) -> Result<Value, String> {
    let port = ensure_backend(&app)?;
    proxy_json(port, "GET", "/history", None, HISTORY_HTTP_TIMEOUT)
}

#[tauri::command(async)]
fn sender_scan(app: tauri::AppHandle, path: String) -> Result<Value, String> {
    let port = ensure_backend(&app)?;
    proxy_json(
        port,
        "POST",
        "/scan",
        Some(json!({ "path": path })),
        MUTATION_HTTP_TIMEOUT,
    )
}

#[tauri::command(async)]
fn sender_send(app: tauri::AppHandle, manifest: Value) -> Result<Value, String> {
    let port = ensure_backend(&app)?;
    proxy_json(port, "POST", "/send", Some(manifest), MUTATION_HTTP_TIMEOUT)
}

#[tauri::command(async)]
fn sender_log_generate(
    app: tauri::AppHandle,
    manifest: Value,
    metadata: Value,
) -> Result<Value, String> {
    let port = ensure_backend(&app)?;
    proxy_json(
        port,
        "POST",
        "/audit/generate",
        Some(json!({ "manifest": manifest, "metadata": metadata })),
        MUTATION_HTTP_TIMEOUT,
    )
}

#[tauri::command(async)]
fn sender_backend_url(app: tauri::AppHandle) -> Result<String, String> {
    let port = ensure_backend(&app)?;
    Ok(backend_url(port))
}

fn ensure_backend(app: &tauri::AppHandle) -> Result<u16, String> {
    let _startup_guard = BACKEND_STARTUP_LOCK
        .lock()
        .expect("backend startup lock failed");

    if let Some(port) = active_backend_port(app) {
        if backend_is_healthy(port) {
            return Ok(port);
        }
    }

    if let Some(port) = tracked_child_port(app) {
        for _ in 0..HEALTH_POLL_ATTEMPTS {
            if backend_is_healthy(port) {
                return Ok(port);
            }
            std::thread::sleep(HEALTH_POLL_DELAY);
        }
        stop_tracked_child(app);
        wait_for_backend_port_to_close(port);
    }

    let port = choose_available_backend_port()?;
    spawn_backend(app, port)?;

    for _ in 0..HEALTH_POLL_ATTEMPTS {
        if backend_is_healthy(port) {
            return Ok(port);
        }
        std::thread::sleep(HEALTH_POLL_DELAY);
    }

    Err(format!(
        "전송 백엔드가 제한 시간 안에 응답하지 않았습니다. {}",
        backend_diagnostics(app)
    ))
}

#[cfg(test)]
fn backend_startup_wait_budget() -> Duration {
    Duration::from_millis(HEALTH_POLL_DELAY.as_millis() as u64 * HEALTH_POLL_ATTEMPTS as u64)
}

fn backend_url(port: u16) -> String {
    format!("http://{BACKEND_HOST}:{port}")
}

fn choose_available_backend_port() -> Result<u16, String> {
    for _ in 0..16 {
        let listener = TcpListener::bind((BACKEND_HOST, 0))
            .map_err(|error| format!("전송 백엔드용 로컬 포트를 확보하지 못했습니다: {error}"))?;
        let port = listener
            .local_addr()
            .map_err(|error| format!("전송 백엔드용 로컬 포트를 확인하지 못했습니다: {error}"))?
            .port();
        drop(listener);
        if port != LEGACY_DEV_BACKEND_PORT {
            return Ok(port);
        }
    }
    Err(format!(
        "전송 백엔드용 로컬 포트를 확보하지 못했습니다: 레거시 개발 포트 {BACKEND_HOST}:{LEGACY_DEV_BACKEND_PORT}만 선택되었습니다."
    ))
}

fn backend_port_accepts_connection(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, CONNECT_TIMEOUT).is_ok()
}

fn wait_for_backend_port_to_close(port: u16) {
    for _ in 0..10 {
        if !backend_port_accepts_connection(port) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn backend_is_healthy(port: u16) -> bool {
    match proxy_json(port, "GET", BACKEND_READY_PATH, None, HEALTH_HTTP_TIMEOUT) {
        Ok(value) => value.get("ok").and_then(Value::as_bool).unwrap_or(false),
        Err(_) => false,
    }
}

fn active_backend_port(app: &tauri::AppHandle) -> Option<u16> {
    let state = app.state::<BackendState>();
    let backend = state.0.lock().expect("backend state lock failed");
    backend.port
}

fn tracked_child_port(app: &tauri::AppHandle) -> Option<u16> {
    let state = app.state::<BackendState>();
    let backend = state.0.lock().expect("backend state lock failed");
    backend.child.as_ref().and(backend.port)
}

fn spawn_backend(app: &tauri::AppHandle, port: u16) -> Result<(), String> {
    {
        let state = app.state::<BackendState>();
        let mut backend = state.0.lock().expect("backend state lock failed");
        backend.termination = None;
        backend.spawn_error = None;
        backend.port = Some(port);
    }

    let sidecar = app
        .shell()
        .sidecar("ship-sender-backend")
        .map_err(|error| {
            let message = format!("전송 백엔드 실행 파일을 찾지 못했습니다: {error}");
            record_spawn_error(app, message.clone());
            message
        })?;

    let command = sidecar
        .args(["--parent-pid".to_string(), std::process::id().to_string()])
        .env("SHIP_SENDER_HOST", BACKEND_HOST)
        .env("SHIP_SENDER_PORT", port.to_string());
    #[cfg(windows)]
    let command = command.env("SHIP_DB_DIR", WINDOWS_SHIP_DB_DIR);

    let (mut rx, child) = command.spawn().map_err(|error| {
        let message = format!("전송 백엔드를 시작하지 못했습니다: {error}");
        record_spawn_error(app, message.clone());
        clear_backend_port(app, port);
        message
    })?;

    {
        let state = app.state::<BackendState>();
        let mut backend = state.0.lock().expect("backend state lock failed");
        backend.generation = backend.generation.wrapping_add(1);
        backend.child = Some(child);
        let generation = backend.generation;

        let app_handle = app.clone();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                record_backend_event(&app_handle, generation, event);
            }
        });
    }

    Ok(())
}

fn record_backend_event(app: &tauri::AppHandle, generation: u64, event: CommandEvent) {
    let state = app.state::<BackendState>();
    let mut backend = state.0.lock().expect("backend state lock failed");
    match event {
        CommandEvent::Stdout(line) => {
            let text = String::from_utf8_lossy(&line).trim().to_string();
            if !text.is_empty() {
                println!("{text}");
                push_log_line(&mut backend.stdout, text);
            }
        }
        CommandEvent::Stderr(line) => {
            let text = String::from_utf8_lossy(&line).trim().to_string();
            if !text.is_empty() {
                eprintln!("{text}");
                push_log_line(&mut backend.stderr, text);
            }
        }
        CommandEvent::Error(error) => {
            let text = format!("sidecar event error: {error}");
            eprintln!("{text}");
            push_log_line(&mut backend.stderr, text);
        }
        CommandEvent::Terminated(payload) => {
            let text = format!(
                "전송 백엔드가 종료되었습니다(code={:?}, signal={:?})",
                payload.code, payload.signal
            );
            eprintln!("{text}");
            if backend.generation == generation {
                backend.termination = Some(text);
                backend.child = None;
                backend.port = None;
            } else {
                push_log_line(
                    &mut backend.stderr,
                    format!("stale sidecar event ignored: {text}"),
                );
            }
        }
        _ => {}
    }
}

fn record_spawn_error(app: &tauri::AppHandle, message: String) {
    let state = app.state::<BackendState>();
    let mut backend = state.0.lock().expect("backend state lock failed");
    backend.spawn_error = Some(message);
}

fn clear_backend_port(app: &tauri::AppHandle, port: u16) {
    let state = app.state::<BackendState>();
    let mut backend = state.0.lock().expect("backend state lock failed");
    if backend.port == Some(port) {
        backend.port = None;
    }
}

fn push_log_line(lines: &mut VecDeque<String>, line: String) {
    if lines.len() == LOG_TAIL_LIMIT {
        lines.pop_front();
    }
    lines.push_back(line);
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some((child, port)) = take_tracked_child(app) {
        request_backend_shutdown(port);
        let _ = child.kill();
    }
}

fn stop_tracked_child(app: &tauri::AppHandle) {
    let child = take_tracked_child(app);
    if let Some((child, _port)) = child {
        let _ = child.kill();
    }
}

fn take_tracked_child(app: &tauri::AppHandle) -> Option<(CommandChild, u16)> {
    let state = app.state::<BackendState>();
    let mut backend = state.0.lock().expect("backend state lock failed");
    let child = backend.child.take()?;
    let port = backend.port.take()?;
    Some((child, port))
}

fn request_backend_shutdown(port: u16) {
    if let Ok(mut stream) = TcpStream::connect((BACKEND_HOST, port)) {
        let _ = stream
            .write_all(b"GET /shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    }
}

fn proxy_json(
    port: u16,
    method: &str,
    path: &str,
    payload: Option<Value>,
    response_timeout: Duration,
) -> Result<Value, String> {
    let body = match payload {
        Some(value) => Some(
            serde_json::to_vec(&value)
                .map_err(|error| format!("전송 요청을 JSON으로 변환하지 못했습니다: {error}"))?,
        ),
        None => None,
    };
    let response = send_http_request(port, method, path, body.as_deref(), response_timeout)?;
    if !(200..300).contains(&response.status) {
        return Err(format_backend_status_error(response.status, &response.body));
    }
    serde_json::from_str(&response.body)
        .map_err(|error| format!("전송 백엔드 응답을 JSON으로 해석하지 못했습니다: {error}"))
}

struct HttpResponse {
    status: u16,
    body: String,
}

fn send_http_request(
    port: u16,
    method: &str,
    path: &str,
    body: Option<&[u8]>,
    response_timeout: Duration,
) -> Result<HttpResponse, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, CONNECT_TIMEOUT).map_err(|error| {
        format!("전송 백엔드 포트({BACKEND_HOST}:{port})에 연결하지 못했습니다: {error}")
    })?;
    stream
        .set_read_timeout(Some(response_timeout))
        .map_err(|error| format!("전송 백엔드 읽기 제한 시간을 설정하지 못했습니다: {error}"))?;
    stream
        .set_write_timeout(Some(CONNECT_TIMEOUT))
        .map_err(|error| format!("전송 백엔드 쓰기 제한 시간을 설정하지 못했습니다: {error}"))?;

    let body_len = body.map_or(0, <[u8]>::len);
    let content_type = if body.is_some() {
        "Content-Type: application/json; charset=utf-8\r\n"
    } else {
        ""
    };
    let request = format!(
        "{method} {path} HTTP/1.1\r\nHost: {BACKEND_HOST}:{port}\r\n{content_type}Content-Length: {body_len}\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| format!("전송 백엔드에 요청을 보내지 못했습니다: {error}"))?;
    if let Some(bytes) = body {
        stream
            .write_all(bytes)
            .map_err(|error| format!("전송 백엔드에 요청 본문을 보내지 못했습니다: {error}"))?;
    }

    let mut response = Vec::new();
    stream
        .read_to_end(&mut response)
        .map_err(|error| format!("전송 백엔드 응답을 읽지 못했습니다: {error}"))?;
    parse_http_response(&response)
}

fn parse_http_response(response: &[u8]) -> Result<HttpResponse, String> {
    let separator = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "전송 백엔드가 올바르지 않은 HTTP 응답을 보냈습니다.".to_string())?;
    let header = std::str::from_utf8(&response[..separator])
        .map_err(|error| format!("전송 백엔드 HTTP 헤더를 읽지 못했습니다: {error}"))?;
    let status_line = header
        .lines()
        .next()
        .ok_or_else(|| "전송 백엔드 HTTP 상태 줄이 비어 있습니다.".to_string())?;
    let status = parse_status_code(status_line)?;
    let body = String::from_utf8(response[separator + 4..].to_vec())
        .map_err(|error| format!("전송 백엔드 응답 본문이 UTF-8이 아닙니다: {error}"))?;
    Ok(HttpResponse { status, body })
}

fn parse_status_code(status_line: &str) -> Result<u16, String> {
    let status = status_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| format!("전송 백엔드 HTTP 상태를 읽지 못했습니다: {status_line}"))?;
    status
        .parse::<u16>()
        .map_err(|error| format!("전송 백엔드 HTTP 상태가 숫자가 아닙니다({status}): {error}"))
}

fn format_backend_status_error(status: u16, body: &str) -> String {
    let backend_error = serde_json::from_str::<Value>(body)
        .ok()
        .and_then(|value| {
            value
                .get("error")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .unwrap_or_else(|| truncate_for_diagnostic(body, 240));
    format!("전송 백엔드 요청이 실패했습니다(HTTP {status}): {backend_error}")
}

fn backend_diagnostics(app: &tauri::AppHandle) -> String {
    let state = app.state::<BackendState>();
    let backend = state.0.lock().expect("backend state lock failed");
    format_diagnostics(
        backend.spawn_error.as_deref(),
        backend.termination.as_deref(),
        &backend.stdout,
        &backend.stderr,
    )
}

fn format_diagnostics(
    spawn_error: Option<&str>,
    termination: Option<&str>,
    stdout: &VecDeque<String>,
    stderr: &VecDeque<String>,
) -> String {
    let mut parts = Vec::new();
    if let Some(error) = spawn_error.filter(|value| !value.is_empty()) {
        parts.push(format!("시작 오류: {error}"));
    }
    if let Some(value) = termination.filter(|value| !value.is_empty()) {
        parts.push(value.to_string());
    }
    if !stderr.is_empty() {
        parts.push(format!(
            "stderr: {}",
            stderr.iter().cloned().collect::<Vec<_>>().join(" | ")
        ));
    }
    if !stdout.is_empty() {
        parts.push(format!(
            "stdout: {}",
            stdout.iter().cloned().collect::<Vec<_>>().join(" | ")
        ));
    }
    if parts.is_empty() {
        "추가 로그가 없습니다.".to_string()
    } else {
        parts.join(" / ")
    }
}

fn truncate_for_diagnostic(value: &str, max_chars: usize) -> String {
    let mut result = String::new();
    for (index, character) in value.chars().enumerate() {
        if index == max_chars {
            result.push('…');
            return result;
        }
        result.push(character);
    }
    result
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .manage(BackendState(Mutex::new(BackendProcess::default())))
        .setup(|app| {
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Err(error) = ensure_backend(&app_handle) {
                    eprintln!("{error}");
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            sender_health,
            sender_backend_url,
            sender_history,
            sender_scan,
            sender_send,
            sender_log_generate
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                stop_backend(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build sender app")
        .run(|app_handle, event| match event {
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                stop_backend(app_handle)
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_http_response_status_and_body() {
        let response =
            parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{\"ok\":true}")
                .expect("response should parse");
        assert_eq!(response.status, 200);
        assert_eq!(response.body, "{\"ok\":true}");
    }

    #[test]
    fn extracts_backend_error_from_json_status_body() {
        assert_eq!(
            format_backend_status_error(400, "{\"error\":\"bad folder\"}"),
            "전송 백엔드 요청이 실패했습니다(HTTP 400): bad folder"
        );
    }

    #[test]
    fn keeps_diagnostic_tail_bounded() {
        let mut lines = VecDeque::new();
        for index in 0..(LOG_TAIL_LIMIT + 2) {
            push_log_line(&mut lines, format!("line {index}"));
        }
        assert_eq!(lines.len(), LOG_TAIL_LIMIT);
        assert_eq!(lines.front().map(String::as_str), Some("line 2"));
    }

    #[test]
    fn formats_empty_diagnostics_in_korean() {
        assert_eq!(
            format_diagnostics(None, None, &VecDeque::new(), &VecDeque::new()),
            "추가 로그가 없습니다."
        );
    }

    #[test]
    fn uses_longer_timeouts_for_slow_backend_work() {
        assert!(HISTORY_HTTP_TIMEOUT > HEALTH_HTTP_TIMEOUT);
        assert!(MUTATION_HTTP_TIMEOUT > HISTORY_HTTP_TIMEOUT);
    }

    #[test]
    fn bounds_history_timeout_for_unresponsive_shared_db() {
        assert!(HISTORY_HTTP_TIMEOUT <= Duration::from_secs(2));
    }

    #[test]
    fn backend_readiness_probe_does_not_use_db_health() {
        assert_eq!(BACKEND_READY_PATH, "/ready");
    }

    #[test]
    fn windows_sidecar_db_dir_uses_forward_slash_unc_path() {
        assert_eq!(WINDOWS_SHIP_DB_DIR, "//Mserver/USA_DB/test_jn/ship_db");
    }

    #[test]
    fn allows_slow_pyinstaller_sidecar_startup() {
        assert!(backend_startup_wait_budget() >= Duration::from_secs(10));
    }

    #[test]
    fn formats_backend_url_with_selected_port() {
        assert_eq!(backend_url(49152), "http://127.0.0.1:49152");
    }

    #[test]
    fn chooses_available_local_backend_port() {
        let port = choose_available_backend_port().expect("port should be available");
        assert_ne!(port, 0);
        assert_ne!(port, LEGACY_DEV_BACKEND_PORT);
        assert!(!backend_port_accepts_connection(port));
    }

    #[test]
    fn keeps_native_backend_off_legacy_dev_port_when_it_is_occupied() {
        let listener = TcpListener::bind((BACKEND_HOST, LEGACY_DEV_BACKEND_PORT)).ok();
        assert!(listener.is_some() || backend_port_accepts_connection(LEGACY_DEV_BACKEND_PORT));
        let port = choose_available_backend_port().expect("dynamic port should be available");
        assert_ne!(port, LEGACY_DEV_BACKEND_PORT);
        drop(listener);
    }
}
