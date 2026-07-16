export type SceneValidation = {
  checked: boolean;
  exists: boolean;
  expected_folder_name: string;
  matched_path: string | null;
  reason: string;
};

export type FileEntry = {
  path: string;
  size: number;
  is_dir: boolean;
  scene_validation?: SceneValidation;
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

export type ShipmentSummary = {
  id: string;
  label: string;
  day: string;
  created_at: string;
  sent_at?: string;
  content_signature?: string;
  file_count: number;
};

export type ShipmentMonth = {
  month: string;
  shipments: ShipmentSummary[];
};

export type ShipmentYear = {
  year: string;
  months: ShipmentMonth[];
};

export type ShipmentTree = {
  years: ShipmentYear[];
};

type GetShipmentOptions = {
  includeSceneValidation?: boolean;
};

const BASE_URL = import.meta.env.VITE_MANAGER_API_URL ?? 'http://127.0.0.1:8770';

export function getGeneratedThumbnailUrl(shipmentId: string, sourcePath: string, filePath: string) {
  const params = new URLSearchParams({ file_path: filePath });
  if (shipmentId.trim() !== '') {
    params.set('shipment_id', shipmentId);
  }
  if (sourcePath.trim() !== '') {
    params.set('source_path', sourcePath);
  }
  return `${BASE_URL}/thumbnail?${params.toString()}`;
}

export async function listShipments(): Promise<ShipmentTree> {
  return getJson<ShipmentTree>('/shipments');
}

export async function getShipment(id: string, options: GetShipmentOptions = {}): Promise<ShipmentManifest> {
  const params = new URLSearchParams({ id });
  if (options.includeSceneValidation === false) {
    params.set('scene_validation', '0');
  }
  return getJson<ShipmentManifest>(`/shipment?${params.toString()}`);
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error ?? 'request failed');
  }
  return data as T;
}
