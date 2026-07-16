import { invoke } from '@tauri-apps/api/core';

export type AuditLogDate = {
  date: string;
};

export type AuditLogEntry = {
  line_number: number;
  schema_version?: number;
  timestamp?: string;
  date?: string;
  action?: string;
  manifest_id?: string;
  folder_name?: string;
  source_path?: string;
  file_count?: number;
  files?: string[];
  note?: string;
  job?: string;
  tk?: string;
  batch?: string;
  ip?: string;
  hostname?: string;
  hostname_source?: string;
};

export type MalformedLogLine = {
  line_number: number;
  message: string;
  raw: string;
};

export type AuditLogReadResult = {
  date: string;
  entries: AuditLogEntry[];
  malformed_count: number;
  malformed_lines: MalformedLogLine[];
};

const isTauriApp = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

export async function listAuditLogDates(): Promise<AuditLogDate[]> {
  if (!isTauriApp) {
    return [];
  }
  return invokeJson<AuditLogDate[]>('list_audit_log_dates');
}

export async function readAuditLogEntries(date: string): Promise<AuditLogReadResult> {
  if (!isTauriApp) {
    throw new Error('전송로그는 Tauri 앱에서 감사 로그 파일을 직접 읽습니다.');
  }
  return invokeJson<AuditLogReadResult>('read_audit_log_entries', { date });
}

async function invokeJson<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(command, args);
  } catch (error) {
    throw new Error(normalizeApiError(error));
  }
}

function normalizeApiError(error: unknown): string {
  if (typeof error === 'string' && error.trim() !== '') {
    return error;
  }
  if (error instanceof Error && error.message.trim() !== '') {
    return error.message;
  }
  if (isErrorRecord(error)) {
    const message = error.message ?? error.error;
    if (typeof message === 'string' && message.trim() !== '') {
      return message;
    }
  }
  return '감사 로그 요청이 실패했습니다.';
}

function isErrorRecord(error: unknown): error is { message?: unknown; error?: unknown } {
  return typeof error === 'object' && error !== null;
}
