import { getCurrentWebview } from '@tauri-apps/api/webview';
import type { UnlistenFn } from '@tauri-apps/api/event';

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export async function listenForFolderDrops(onDrop: (paths: string[]) => void): Promise<UnlistenFn> {
  if (!window.__TAURI_INTERNALS__) {
    return () => undefined;
  }
  const webview = getCurrentWebview();
  return webview.onDragDropEvent((event) => {
    if (event.payload.type === 'drop' && event.payload.paths.length > 0) {
      onDrop(event.payload.paths);
    }
  });
}
