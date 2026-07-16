import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification';

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export async function notify(title: string, body: string): Promise<void> {
  if (!window.__TAURI_INTERNALS__) {
    return;
  }
  let permissionGranted = await isPermissionGranted();
  if (!permissionGranted) {
    const permission = await requestPermission();
    permissionGranted = permission === 'granted';
  }
  if (permissionGranted) {
    sendNotification({ title, body });
  }
}
