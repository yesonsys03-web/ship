#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

const APP_DATA_DIR_NAME: &str = "Ship";
const AUDIT_LOG_DIR_NAME: &str = "audit_logs";
const MAX_MALFORMED_SAMPLES: usize = 20;
const MAX_ENRICHED_FILES: usize = 80;
const MAX_RECURSIVE_DIRS: usize = 96;
const MAX_RECURSIVE_DEPTH: usize = 4;

#[derive(Debug, Serialize, PartialEq, Eq)]
struct AuditLogDate {
    date: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct AuditLogEntry {
    line_number: usize,
    schema_version: Option<u64>,
    timestamp: Option<String>,
    date: Option<String>,
    action: Option<String>,
    manifest_id: Option<String>,
    folder_name: Option<String>,
    source_path: Option<String>,
    file_count: Option<u64>,
    files: Vec<String>,
    note: Option<String>,
    job: Option<String>,
    tk: Option<String>,
    batch: Option<String>,
    ip: Option<String>,
    hostname: Option<String>,
    hostname_source: Option<String>,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct MalformedLogLine {
    line_number: usize,
    message: String,
    raw: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct AuditLogReadResult {
    date: String,
    entries: Vec<AuditLogEntry>,
    malformed_count: usize,
    malformed_lines: Vec<MalformedLogLine>,
}

#[tauri::command]
fn list_audit_log_dates() -> Result<Vec<AuditLogDate>, String> {
    list_audit_log_dates_in(&default_audit_log_dir())
        .map_err(|error| format!("감사 로그 날짜를 불러오지 못했습니다: {error}"))
}

#[tauri::command]
fn read_audit_log_entries(date: String) -> Result<AuditLogReadResult, String> {
    read_audit_log_entries_in(&default_audit_log_dir(), &date)
        .map_err(|error| format!("{date} 감사 로그를 읽지 못했습니다: {error}"))
}

fn default_audit_log_dir() -> PathBuf {
    audit_log_dir_from_configured_env(
        std::env::var("SHIP_AUDIT_LOG_DIR").ok(),
        local_audit_log_dir(),
    )
}

fn audit_log_dir_from_configured_env(
    configured_dir: Option<String>,
    local_dir: Option<PathBuf>,
) -> PathBuf {
    if let Some(configured_dir) = configured_dir {
        let trimmed = configured_dir.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    local_dir.unwrap_or_else(|| {
        PathBuf::from("data")
            .join(APP_DATA_DIR_NAME)
            .join(AUDIT_LOG_DIR_NAME)
    })
}

#[cfg(windows)]
fn local_audit_log_dir() -> Option<PathBuf> {
    std::env::var("LOCALAPPDATA")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("APPDATA")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .map(|directory| {
            PathBuf::from(directory)
                .join(APP_DATA_DIR_NAME)
                .join(AUDIT_LOG_DIR_NAME)
        })
}

#[cfg(target_os = "macos")]
fn local_audit_log_dir() -> Option<PathBuf> {
    std::env::var("HOME")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(|home| {
            PathBuf::from(home)
                .join("Library")
                .join("Application Support")
                .join(APP_DATA_DIR_NAME)
                .join(AUDIT_LOG_DIR_NAME)
        })
}

#[cfg(all(not(windows), not(target_os = "macos")))]
fn local_audit_log_dir() -> Option<PathBuf> {
    if let Ok(data_home) = std::env::var("XDG_DATA_HOME") {
        let trimmed = data_home.trim();
        if !trimmed.is_empty() {
            return Some(
                PathBuf::from(trimmed)
                    .join(APP_DATA_DIR_NAME)
                    .join(AUDIT_LOG_DIR_NAME),
            );
        }
    }

    std::env::var("HOME")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(|home| {
            PathBuf::from(home)
                .join(".local")
                .join("share")
                .join(APP_DATA_DIR_NAME)
                .join(AUDIT_LOG_DIR_NAME)
        })
}

fn list_audit_log_dates_in(log_dir: &Path) -> Result<Vec<AuditLogDate>, String> {
    if !log_dir.exists() {
        return Ok(Vec::new());
    }
    if !log_dir.is_dir() {
        return Err(format!(
            "로그 경로가 폴더가 아닙니다: {}",
            log_dir.display()
        ));
    }

    let mut dates = Vec::new();
    for entry in fs::read_dir(log_dir).map_err(|error| error.to_string())? {
        let entry = entry.map_err(|error| error.to_string())?;
        if !entry
            .file_type()
            .map_err(|error| error.to_string())?
            .is_file()
        {
            continue;
        }
        let file_name = entry.file_name();
        let file_name = file_name.to_string_lossy();
        if let Some(date) = file_name.strip_suffix(".jsonl") {
            if is_valid_audit_date(date) {
                dates.push(AuditLogDate {
                    date: date.to_string(),
                });
            }
        }
    }

    dates.sort_by(|first, second| second.date.cmp(&first.date));
    Ok(dates)
}

fn read_audit_log_entries_in(log_dir: &Path, date: &str) -> Result<AuditLogReadResult, String> {
    if !is_valid_audit_date(date) {
        return Err("날짜는 YYYY-MM-DD 형식이어야 합니다.".to_string());
    }

    let log_path = log_path_for_date(log_dir, date);
    let file =
        fs::File::open(&log_path).map_err(|error| format!("{}: {error}", log_path.display()))?;
    let mut reader = BufReader::new(file);
    let mut line_bytes = Vec::new();
    let mut line_number = 0;
    let mut entries = Vec::new();
    let mut malformed_lines = Vec::new();
    let mut malformed_count = 0;

    loop {
        line_bytes.clear();
        let bytes_read = reader
            .read_until(b'\n', &mut line_bytes)
            .map_err(|error| error.to_string())?;
        if bytes_read == 0 {
            break;
        }
        line_number += 1;
        trim_line_ending(&mut line_bytes);
        let raw_line = String::from_utf8_lossy(&line_bytes).to_string();
        if raw_line.trim().is_empty() {
            continue;
        }

        match parse_audit_log_entry(&raw_line, line_number) {
            Ok(mut entry) => {
                enrich_audit_log_entry_files(&mut entry);
                entries.push(entry);
            }
            Err(message) => {
                malformed_count += 1;
                if malformed_lines.len() < MAX_MALFORMED_SAMPLES {
                    malformed_lines.push(MalformedLogLine {
                        line_number,
                        message,
                        raw: raw_line,
                    });
                }
            }
        }
    }

    Ok(AuditLogReadResult {
        date: date.to_string(),
        entries,
        malformed_count,
        malformed_lines,
    })
}

fn parse_audit_log_entry(raw_line: &str, line_number: usize) -> Result<AuditLogEntry, String> {
    let value: Value = serde_json::from_str(raw_line).map_err(|error| error.to_string())?;
    let object = value
        .as_object()
        .ok_or_else(|| "JSON object가 아닙니다.".to_string())?;

    let source_path = optional_string(object.get("source_path"));
    let saved_files = optional_string_array(object.get("files"))
        .or_else(|| optional_string_array(object.get("file_paths")))
        .unwrap_or_default();

    Ok(AuditLogEntry {
        line_number,
        schema_version: optional_u64(object.get("schema_version")),
        timestamp: optional_string(object.get("timestamp")),
        date: optional_string(object.get("date")),
        action: optional_string(object.get("action")),
        manifest_id: optional_string(object.get("manifest_id")),
        folder_name: optional_string(object.get("folder_name")),
        source_path: source_path.clone(),
        file_count: optional_u64(object.get("file_count")),
        files: display_file_paths(saved_files, source_path.as_deref()),
        note: optional_string(object.get("note")),
        job: optional_string(object.get("job")),
        tk: optional_string(object.get("tk")),
        batch: optional_string(object.get("batch")),
        ip: optional_string(object.get("ip")),
        hostname: optional_string(object.get("hostname")),
        hostname_source: optional_string(object.get("hostname_source")),
    })
}

fn optional_string_array(value: Option<&Value>) -> Option<Vec<String>> {
    let values = match value {
        Some(Value::Array(values)) => values,
        _ => return None,
    };
    Some(values.iter().filter_map(value_to_string).collect())
}

fn value_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.clone()),
        Value::Number(number) => Some(number.to_string()),
        Value::Bool(flag) => Some(flag.to_string()),
        _ => None,
    }
}

fn display_file_paths(files: Vec<String>, source_path: Option<&str>) -> Vec<String> {
    let mut display_files = Vec::new();
    for file in files {
        let display_file = display_file_path(&file, source_path);
        if display_file.is_empty() || display_files.contains(&display_file) {
            continue;
        }
        display_files.push(display_file);
        if display_files.len() >= MAX_ENRICHED_FILES {
            break;
        }
    }
    display_files
}

fn display_file_path(file: &str, source_path: Option<&str>) -> String {
    let trimmed = file.trim();
    if trimmed.is_empty() {
        return String::new();
    }

    if source_path.map(is_bobs_source_path).unwrap_or(false) {
        return clean_bobs_file_name(trimmed);
    }

    let file_path = Path::new(trimmed);
    if file_path.is_absolute() {
        if let Some(source_path) = source_path {
            let source = Path::new(source_path);
            if let Ok(relative_path) = file_path.strip_prefix(source) {
                return path_to_display_string(relative_path);
            }
        }
        return file_path
            .file_name()
            .map(|name| name.to_string_lossy().to_string())
            .unwrap_or_else(|| trimmed.to_string());
    }

    trimmed.to_string()
}

fn is_bobs_source_path(source_path: &str) -> bool {
    source_path.trim_start().starts_with("bobs://")
}

fn is_bobs_manifest_id(manifest_id: &str) -> bool {
    let trimmed = manifest_id.trim_start().to_ascii_lowercase();
    trimmed.starts_with("bobs:") && trimmed.contains(":batch:")
}

fn clean_bobs_file_name(file: &str) -> String {
    let name = file.rsplit('/').next().unwrap_or(file).trim();
    name.strip_suffix(".bobs-scene").unwrap_or(name).to_string()
}

fn derive_bobs_scene_names(entry: &AuditLogEntry) -> Vec<String> {
    let mut scene_names = Vec::new();
    if let Some(source_path) = entry.source_path.as_deref() {
        append_bobs_scene_names_from_source_path(source_path, &mut scene_names);
    }
    if scene_names.is_empty() {
        if let Some(manifest_id) = entry.manifest_id.as_deref() {
            append_bobs_scene_names_from_manifest_id(manifest_id, &mut scene_names);
        }
    }
    scene_names
}

fn append_bobs_scene_names_from_source_path(source_path: &str, scene_names: &mut Vec<String>) {
    let trimmed = source_path.trim();
    let Some(path) = trimmed.strip_prefix("bobs://") else {
        return;
    };
    let segments: Vec<&str> = path
        .split('/')
        .filter(|segment| !segment.trim().is_empty())
        .collect();
    let Some(batch_index) = segments
        .iter()
        .position(|segment| segment.eq_ignore_ascii_case("batch"))
    else {
        return;
    };
    for segment in segments.iter().skip(batch_index + 1) {
        append_bobs_scene_names_from_segment(segment, scene_names);
    }
}

fn append_bobs_scene_names_from_manifest_id(manifest_id: &str, scene_names: &mut Vec<String>) {
    let marker = ":batch:";
    let lower_manifest_id = manifest_id.to_ascii_lowercase();
    let Some(marker_index) = lower_manifest_id.find(marker) else {
        return;
    };
    for segment in manifest_id[(marker_index + marker.len())..].split('/') {
        append_bobs_scene_names_from_segment(segment, scene_names);
    }
}

fn append_bobs_scene_names_from_segment(segment: &str, scene_names: &mut Vec<String>) {
    for scene_name in segment.split('+').filter_map(normalize_bobs_scene_name) {
        if scene_names.len() >= MAX_ENRICHED_FILES {
            return;
        }
        if !scene_names.contains(&scene_name) {
            scene_names.push(scene_name);
        }
    }
}

fn normalize_bobs_scene_name(raw_scene_name: &str) -> Option<String> {
    let without_query = raw_scene_name.split('?').next().unwrap_or(raw_scene_name);
    let without_fragment = without_query.split('#').next().unwrap_or(without_query);
    let scene_name = clean_bobs_file_name(without_fragment).trim().to_string();
    is_bobs_scene_name(&scene_name).then_some(scene_name)
}

fn is_bobs_scene_name(scene_name: &str) -> bool {
    let upper_scene_name = scene_name.to_ascii_uppercase();
    let Some((sequence, scene)) = upper_scene_name.split_once("_S") else {
        return false;
    };
    is_bobs_sequence_key(sequence) && is_bobs_scene_number(scene)
}

fn is_bobs_sequence_key(sequence: &str) -> bool {
    let bytes = sequence.as_bytes();
    if bytes.len() < 2 || !bytes[0].is_ascii_digit() || !bytes[1].is_ascii_digit() {
        return false;
    }
    let suffix = &sequence[2..];
    suffix.is_empty()
        || (suffix.len() == 1 && suffix.as_bytes()[0].is_ascii_alphabetic())
        || (suffix.starts_with('-')
            && suffix.len() > 1
            && suffix[1..]
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-'))
}

fn is_bobs_scene_number(scene: &str) -> bool {
    let digit_count = scene.bytes().take_while(u8::is_ascii_digit).count();
    digit_count >= 2
        && scene[digit_count..]
            .bytes()
            .all(|byte| byte.is_ascii_alphabetic())
}

fn enrich_audit_log_entry_files(entry: &mut AuditLogEntry) {
    if !entry.files.is_empty() {
        return;
    }
    let is_bobs_entry = entry
        .source_path
        .as_deref()
        .map(is_bobs_source_path)
        .unwrap_or(false)
        || entry
            .manifest_id
            .as_deref()
            .map(is_bobs_manifest_id)
            .unwrap_or(false);
    if is_bobs_entry {
        entry.files = derive_bobs_scene_names(entry);
        return;
    }
    let Some(source_path) = entry.source_path.as_deref() else {
        return;
    };
    let source = Path::new(source_path);
    if !source.is_dir() {
        return;
    }
    entry.files = discover_source_files(source, entry.file_count);
}

fn discover_source_files(source: &Path, file_count: Option<u64>) -> Vec<String> {
    let direct_files = direct_child_files(source);
    if !direct_files.is_empty() {
        return direct_files;
    }
    if file_count.unwrap_or(0) == 0 {
        return Vec::new();
    }
    recursive_child_files(source)
}

fn direct_child_files(source: &Path) -> Vec<String> {
    let mut files = Vec::new();
    let Ok(children) = fs::read_dir(source) else {
        return files;
    };
    for child in children.flatten() {
        if files.len() >= MAX_ENRICHED_FILES {
            break;
        }
        if child
            .file_type()
            .map(|file_type| file_type.is_file())
            .unwrap_or(false)
        {
            files.push(child.file_name().to_string_lossy().to_string());
        }
    }
    files.sort();
    files
}

fn recursive_child_files(source: &Path) -> Vec<String> {
    let mut files = Vec::new();
    let mut stack = vec![(source.to_path_buf(), 0usize)];
    let mut visited_dirs = 0usize;

    while let Some((directory, depth)) = stack.pop() {
        if files.len() >= MAX_ENRICHED_FILES
            || visited_dirs >= MAX_RECURSIVE_DIRS
            || depth >= MAX_RECURSIVE_DEPTH
        {
            continue;
        }
        visited_dirs += 1;
        let Ok(children) = fs::read_dir(&directory) else {
            continue;
        };
        let mut child_directories = Vec::new();
        for child in children.flatten() {
            let Ok(file_type) = child.file_type() else {
                continue;
            };
            if file_type.is_file() {
                if let Ok(relative_path) = child.path().strip_prefix(source) {
                    files.push(path_to_display_string(relative_path));
                }
                if files.len() >= MAX_ENRICHED_FILES {
                    break;
                }
            } else if file_type.is_dir() {
                child_directories.push(child.path());
            }
        }
        child_directories.sort();
        for child_directory in child_directories.into_iter().rev() {
            stack.push((child_directory, depth + 1));
        }
    }

    files.sort();
    files.dedup();
    files.truncate(MAX_ENRICHED_FILES);
    files
}

fn path_to_display_string(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/")
}

fn optional_string(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::String(text)) => Some(text.clone()),
        Some(Value::Number(number)) => Some(number.to_string()),
        Some(Value::Bool(flag)) => Some(flag.to_string()),
        _ => None,
    }
}

fn optional_u64(value: Option<&Value>) -> Option<u64> {
    match value {
        Some(Value::Number(number)) => number.as_u64(),
        Some(Value::String(text)) => text.parse::<u64>().ok(),
        _ => None,
    }
}

fn log_path_for_date(log_dir: &Path, date: &str) -> PathBuf {
    log_dir.join(format!("{date}.jsonl"))
}

fn trim_line_ending(line: &mut Vec<u8>) {
    if line.last() == Some(&b'\n') {
        line.pop();
    }
    if line.last() == Some(&b'\r') {
        line.pop();
    }
}

fn is_valid_audit_date(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.len() != 10 || bytes[4] != b'-' || bytes[7] != b'-' {
        return false;
    }
    if !bytes
        .iter()
        .enumerate()
        .all(|(index, byte)| index == 4 || index == 7 || byte.is_ascii_digit())
    {
        return false;
    }
    let year = parse_date_number(&value[0..4]);
    let month = parse_date_number(&value[5..7]);
    let day = parse_date_number(&value[8..10]);
    match (year, month, day) {
        (Some(year), Some(month), Some(day)) => {
            month >= 1 && month <= 12 && day >= 1 && day <= days_in_month(year, month)
        }
        _ => false,
    }
}

fn parse_date_number(value: &str) -> Option<u32> {
    value.parse::<u32>().ok()
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

fn is_leap_year(year: u32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            list_audit_log_dates,
            read_audit_log_entries
        ])
        .run(tauri::generate_context!())
        .expect("failed to build log viewer app");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_log_dir(test_name: &str) -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time should be after unix epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "ship-log-viewer-{test_name}-{}-{timestamp}",
            std::process::id()
        ));
        fs::create_dir_all(&path).expect("temp log dir should be created");
        path
    }

    #[test]
    fn lists_valid_jsonl_dates_newest_first() {
        let log_dir = make_temp_log_dir("dates");
        fs::write(log_dir.join("2026-07-08.jsonl"), "").expect("date file should write");
        fs::write(log_dir.join("2026-07-09.jsonl"), "").expect("date file should write");
        fs::write(log_dir.join("2026-13-01.jsonl"), "").expect("invalid date file should write");
        fs::write(log_dir.join("notes.txt"), "").expect("non-jsonl file should write");

        let dates = list_audit_log_dates_in(&log_dir).expect("dates should list");
        assert_eq!(
            dates,
            vec![
                AuditLogDate {
                    date: "2026-07-09".to_string()
                },
                AuditLogDate {
                    date: "2026-07-08".to_string()
                },
            ]
        );

        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn missing_log_dir_lists_empty_dates() {
        let log_dir = make_temp_log_dir("missing");
        fs::remove_dir_all(&log_dir).expect("temp log dir should be removed");

        let dates = list_audit_log_dates_in(&log_dir).expect("missing dir should be empty");
        assert!(dates.is_empty());
    }

    #[test]
    fn configured_audit_log_dir_overrides_local_default() {
        let configured = PathBuf::from("/tmp/configured-audit");
        let local = PathBuf::from("/tmp/local-audit");

        assert_eq!(
            audit_log_dir_from_configured_env(
                Some(configured.to_string_lossy().to_string()),
                Some(local)
            ),
            configured
        );
    }

    #[test]
    fn blank_configured_audit_log_dir_uses_local_default() {
        let local = PathBuf::from("/tmp/local-audit");

        assert_eq!(
            audit_log_dir_from_configured_env(Some("  ".to_string()), Some(local.clone())),
            local
        );
    }

    #[test]
    fn missing_local_audit_log_dir_uses_project_fallback() {
        assert_eq!(
            audit_log_dir_from_configured_env(None, None),
            PathBuf::from("data")
                .join(APP_DATA_DIR_NAME)
                .join(AUDIT_LOG_DIR_NAME)
        );
    }

    #[test]
    fn reads_entries_and_reports_malformed_lines() {
        let log_dir = make_temp_log_dir("read");
        let log = r#"{"schema_version":1,"timestamp":"2026-07-09T08:00:00Z","date":"2026-07-09","action":"generate","manifest_id":"m1","folder_name":"밥스버거 FASA03 TK1 14개 씬","source_path":"bobs://FASA03/TK1","file_count":14,"note":"메모","job":"FASA03","tk":"1","batch":"","ip":"192.0.2.10","hostname":"edit-01","hostname_source":"hosts"}
not-json
[]
{"schema_version":"1","timestamp":"2026-07-09T08:30:00Z","date":"2026-07-09","action":"send","manifest_id":"m2","folder_name":"헤즈빈호텔 304화","source_path":"/shipping/Hazbin","file_count":"5","note":"","job":"","tk":"","batch":"2","ip":"unknown","hostname":"mac-mini","hostname_source":"socket"}
"#;
        fs::write(log_dir.join("2026-07-09.jsonl"), log).expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");
        assert_eq!(result.entries.len(), 2);
        assert_eq!(result.malformed_count, 2);
        assert_eq!(result.entries[0].line_number, 1);
        assert_eq!(result.entries[0].action.as_deref(), Some("generate"));
        assert_eq!(result.entries[0].hostname.as_deref(), Some("edit-01"));
        assert_eq!(result.entries[1].file_count, Some(5));
        assert_eq!(result.malformed_lines[0].line_number, 2);
        assert_eq!(result.malformed_lines[1].message, "JSON object가 아닙니다.");

        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn reads_saved_audit_file_list_as_display_names() {
        let log_dir = make_temp_log_dir("saved-files");
        let source_dir = make_temp_log_dir("saved-source");
        let nested_file = source_dir
            .join("OSRO_mov")
            .join("HH0304_040_0100_OSRO_v01.mov");
        fs::create_dir_all(
            nested_file
                .parent()
                .expect("nested file parent should exist"),
        )
        .expect("nested dir should create");
        fs::write(&nested_file, "mov").expect("nested file should write");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "send",
            "manifest_id": "ship-saved-files",
            "folder_name": "헤즈빈호텔 304화",
            "source_path": source_dir.to_string_lossy(),
            "file_count": 2,
            "files": [nested_file.to_string_lossy(), "loose-reference.txt"],
            "note": "",
            "job": "",
            "tk": "",
            "batch": "",
            "ip": "unknown",
            "hostname": "mac-mini",
            "hostname_source": "socket"
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(
            result.entries[0].files,
            vec![
                "OSRO_mov/HH0304_040_0100_OSRO_v01.mov",
                "loose-reference.txt"
            ]
        );
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
        fs::remove_dir_all(source_dir).expect("temp source dir should be removed");
    }

    #[test]
    fn cleans_saved_bobs_audit_file_list() {
        let entry = parse_audit_log_entry(
            r#"{"source_path":"bobs://Bobs_Burgers/FASA03/batch/TK7","file_count":2,"files":["FASA03/TK7/03A_S01.bobs-scene","FASA03/TK7/03A_S02.bobs-scene"]}"#,
            1,
        )
        .expect("bobs entry should parse");

        assert_eq!(entry.files, vec!["03A_S01", "03A_S02"]);
    }

    #[test]
    fn enriches_old_bobs_entry_with_source_path_scene_name() {
        let log_dir = make_temp_log_dir("old-bobs-source-scene");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "generate",
            "manifest_id": "bobs:Bobs_Burgers:FASA10:batch:TK03/15A_S12",
            "folder_name": "밥스버거 FASA10 TK03 1개 씬",
            "source_path": "bobs://Bobs_Burgers/FASA10/batch/TK03/15A_S12",
            "file_count": 1
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(result.entries[0].files, vec!["15A_S12"]);
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn enriches_old_bobs_entry_with_plus_separated_source_path_scenes() {
        let log_dir = make_temp_log_dir("old-bobs-source-plus-scenes");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "generate",
            "manifest_id": "bobs:Bobs_Burgers:FASA03:batch:03A_S01+03A_S02",
            "folder_name": "밥스버거 FASA03 2개 씬",
            "source_path": "bobs://Bobs_Burgers/FASA03/batch/03A_S01+03A_S02",
            "file_count": 2
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(result.entries[0].files, vec!["03A_S01", "03A_S02"]);
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn enriches_old_bobs_entry_from_manifest_id_when_source_path_has_no_scene() {
        let log_dir = make_temp_log_dir("old-bobs-manifest-scenes");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "generate",
            "manifest_id": "bobs:Bobs_Burgers:FASA10:batch:TK03/15A_S12+15A_S13",
            "folder_name": "밥스버거 FASA10 TK03 2개 씬",
            "source_path": "bobs://Bobs_Burgers/FASA10/batch/TK03",
            "file_count": 2
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(result.entries[0].files, vec!["15A_S12", "15A_S13"]);
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn enriches_old_bobs_entry_from_manifest_id_without_source_path() {
        let log_dir = make_temp_log_dir("old-bobs-manifest-no-source");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "generate",
            "manifest_id": "bobs:Bobs_Burgers:FASA03:batch:03A_S01+03A_S02",
            "folder_name": "밥스버거 FASA03 2개 씬",
            "file_count": 2
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(result.entries[0].files, vec!["03A_S01", "03A_S02"]);
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn enriches_old_entry_with_direct_source_files() {
        let log_dir = make_temp_log_dir("direct-files-log");
        let source_dir = make_temp_log_dir("direct-files-source");
        fs::write(source_dir.join("alpha.mov"), "alpha").expect("alpha file should write");
        fs::write(source_dir.join("bravo.txt"), "bravo").expect("bravo file should write");
        fs::create_dir_all(source_dir.join("nested")).expect("nested dir should create");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "send",
            "manifest_id": "ship-old-direct",
            "folder_name": "2026_0430",
            "source_path": source_dir.to_string_lossy(),
            "file_count": 2
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(result.entries[0].files, vec!["alpha.mov", "bravo.txt"]);
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
        fs::remove_dir_all(source_dir).expect("temp source dir should be removed");
    }

    #[test]
    fn enriches_old_entry_with_bounded_recursive_files_when_children_are_folders() {
        let log_dir = make_temp_log_dir("recursive-files-log");
        let source_dir = make_temp_log_dir("recursive-files-source");
        let first_file = source_dir
            .join("OSRO_mov")
            .join("HH0304_040_0100_OSRO_v01.mov");
        let second_file = source_dir.join("preview").join("slate.png");
        fs::create_dir_all(first_file.parent().expect("first parent should exist"))
            .expect("first dir should create");
        fs::create_dir_all(second_file.parent().expect("second parent should exist"))
            .expect("second dir should create");
        fs::write(first_file, "mov").expect("first file should write");
        fs::write(second_file, "png").expect("second file should write");
        let log_line = serde_json::json!({
            "schema_version": 1,
            "timestamp": "2026-07-09T08:00:00Z",
            "date": "2026-07-09",
            "action": "send",
            "manifest_id": "ship-old-recursive",
            "folder_name": "2026_0430",
            "source_path": source_dir.to_string_lossy(),
            "file_count": 2
        });
        fs::write(log_dir.join("2026-07-09.jsonl"), format!("{log_line}\n"))
            .expect("log file should write");

        let result = read_audit_log_entries_in(&log_dir, "2026-07-09").expect("log should read");

        assert_eq!(
            result.entries[0].files,
            vec!["OSRO_mov/HH0304_040_0100_OSRO_v01.mov", "preview/slate.png"]
        );
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
        fs::remove_dir_all(source_dir).expect("temp source dir should be removed");
    }

    #[test]
    fn rejects_invalid_selected_date() {
        let log_dir = make_temp_log_dir("invalid-date");
        let error = read_audit_log_entries_in(&log_dir, "../../2026-07-09")
            .expect_err("invalid date should fail");
        assert!(error.contains("YYYY-MM-DD"));
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }

    #[test]
    fn reports_missing_date_file_as_read_error() {
        let log_dir = make_temp_log_dir("missing-file");
        let error = read_audit_log_entries_in(&log_dir, "2026-07-09")
            .expect_err("missing file should fail");
        assert!(error.contains("2026-07-09.jsonl"));
        fs::remove_dir_all(log_dir).expect("temp log dir should be removed");
    }
}
