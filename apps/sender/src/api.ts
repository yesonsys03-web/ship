import { invoke } from '@tauri-apps/api/core';

export type FileEntry = {
  path: string;
  size: number;
  is_dir: boolean;
};

export type ShipmentManifest = {
  id: string;
  source_path: string;
  folder_name: string;
  created_at: string;
  sent_at?: string;
  note: string;
  files: FileEntry[];
};

export type SenderDbHealth = {
  path: string;
  exists: boolean;
  parent_exists: boolean;
  history_count: number;
  error?: string;
  diagnostics?: string[];
};

export type SenderHealth = {
  ok: boolean;
  role: 'sender';
  db: SenderDbHealth;
};

export type BobsCatalogJobs = {
  environment: string;
  root: string | null;
  jobs: string[];
  warnings: string[];
};

export type BobsCatalogJob = {
  environment: string;
  job: string;
  root: string | null;
  scene_db_path: string | null;
  status: string;
  scenes: string[];
  sequences: Record<string, string[]>;
  warnings: string[];
};

export type BobsRetakePdfDate = {
  year: number;
  month: number;
  day: number;
};

export type BobsRetakePdfRow = {
  sequence: string;
  scene_number: string;
  scene_label: string;
  tk: string;
};

export type BobsRetakePdfParseOptions = {
  excel_paths?: string[];
  due_date_path?: string;
};

export type BobsRetakePdfParseResult = {
  matched: boolean;
  recognized?: boolean;
  job: string;
  due_date: BobsRetakePdfDate | null;
  rows: BobsRetakePdfRow[];
  error: string;
};

const FALLBACK_BASE_URL = import.meta.env.VITE_SENDER_API_URL ?? 'http://127.0.0.1:8765';
const isTauriApp = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

export function getGeneratedThumbnailUrl(backendBaseUrl: string, shipmentId: string, sourcePath: string, filePath: string) {
  const params = new URLSearchParams({ file_path: filePath });
  if (shipmentId.trim() !== '') {
    params.set('shipment_id', shipmentId);
  }
  if (sourcePath.trim() !== '') {
    params.set('source_path', sourcePath);
  }
  return `${backendBaseUrl}/thumbnail?${params.toString()}`;
}

export async function getSenderBackendUrl(): Promise<string> {
  if (!isTauriApp) {
    return FALLBACK_BASE_URL;
  }
  return invokeJson<string>('sender_backend_url');
}

export async function scanFolder(path: string): Promise<ShipmentManifest> {
  if (isTauriApp) {
    return invokeJson<ShipmentManifest>('sender_scan', { path });
  }
  return postJson<ShipmentManifest>('/scan', { path });
}

export async function fetchSentHistory(): Promise<ShipmentManifest[]> {
  if (isTauriApp) {
    return invokeJson<ShipmentManifest[]>('sender_history');
  }
  return getJson<ShipmentManifest[]>('/history');
}

export async function fetchSenderHealth(): Promise<SenderHealth> {
  if (isTauriApp) {
    return invokeJson<SenderHealth>('sender_health');
  }
  return getJson<SenderHealth>('/health');
}

export type SendAuditAction = 'send' | 'revision';

export async function sendManifest(manifest: ShipmentManifest, action: SendAuditAction = 'send'): Promise<{ ok: boolean }> {
  if (isTauriApp) {
    return invokeJson<{ ok: boolean }>('sender_send', { manifest, action });
  }
  return postJson<{ ok: boolean }>('/send', { manifest, action });
}

export async function fetchBobsCatalogJobs(): Promise<BobsCatalogJobs> {
  await ensureSenderBackend();
  return getJson<BobsCatalogJobs>('/bobs/catalog/jobs');
}

export async function fetchBobsCatalogJob(job: string): Promise<BobsCatalogJob> {
  await ensureSenderBackend();
  const params = new URLSearchParams({ job });
  return getJson<BobsCatalogJob>(`/bobs/catalog/job?${params.toString()}`);
}

export async function parseBobsRetakePdf(path: string, options: BobsRetakePdfParseOptions = {}): Promise<BobsRetakePdfParseResult> {
  await ensureSenderBackend();
  return postJson<BobsRetakePdfParseResult>('/bobs/retake-pdf', { path, ...options });
}

async function ensureSenderBackend(): Promise<void> {
  if (isTauriApp) {
    await fetchSenderHealth();
  }
}

async function invokeJson<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(command, args);
  } catch (error) {
    throw new Error(normalizeApiError(error));
  }
}

async function getJson<T>(path: string): Promise<T> {
  const baseUrl = await getSenderBackendUrl();
  const response = await fetch(`${baseUrl}${path}`).catch((error: unknown) => {
    throw new Error(`전송 백엔드에 연결하지 못했습니다: ${normalizeApiError(error)}`);
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error ?? 'request failed');
  }
  return data as T;
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const baseUrl = await getSenderBackendUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch((error: unknown) => {
    throw new Error(`전송 백엔드에 연결하지 못했습니다: ${normalizeApiError(error)}`);
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error ?? 'request failed');
  }
  return data as T;
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
  return '전송 백엔드 요청이 실패했습니다.';
}

function isErrorRecord(error: unknown): error is { message?: unknown; error?: unknown } {
  return typeof error === 'object' && error !== null;
}
