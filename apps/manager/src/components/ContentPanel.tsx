import { useEffect, useMemo, useState, type CSSProperties, type ReactElement } from 'react';
import { getGeneratedThumbnailUrl, type ShipmentManifest } from '../api';
import { getBasename, getManifestDisplayTitle, getPathSegments, getWorkBackgroundClassName, getWorkColorClassName, getWorkTitle } from '../shipmentTitles';

type HighlightPart = string | ReactElement;

type ContentPanelProps = {
  manifest: ShipmentManifest | null;
  searchQuery: string;
};

const imageExtensions = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'avif', 'heic', 'heif']);
const generatedThumbnailExtensions = new Set(['mov', 'mp4', 'm4v', 'webm', 'psd', 'psb']);
const bobsSceneSuffix = '.bobs-scene';

type PreviewKind = 'image' | 'generated';

type FilePreview = {
  kind: PreviewKind;
  src: string;
};

type ManifestFile = ShipmentManifest['files'][number];

type TreeNodeKind = 'folder' | 'file';

type TreeNode = {
  path: string;
  name: string;
  kind: TreeNodeKind;
  depth: number;
  file: ManifestFile | null;
  children: Map<string, TreeNode>;
  descendantFileCount: number;
};

type TreeRow = {
  path: string;
  name: string;
  kind: TreeNodeKind;
  depth: number;
  file: ManifestFile;
  descendantFileCount: number;
  childFolderNames: string[];
  childFileNames: string[];
  hasChildren: boolean;
};

type TreeRowStyle = CSSProperties & {
  '--tree-depth': number;
};

function renderHighlightedText(text: string, query: string): HighlightPart[] | string {
  const searchTerm = query.trim();
  if (searchTerm === '') {
    return text;
  }

  const normalizedText = text.toLocaleLowerCase('ko-KR');
  const normalizedSearchTerm = searchTerm.toLocaleLowerCase('ko-KR');
  const parts: HighlightPart[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    const matchIndex = normalizedText.indexOf(normalizedSearchTerm, cursor);
    if (matchIndex === -1) {
      break;
    }

    if (matchIndex > cursor) {
      parts.push(text.slice(cursor, matchIndex));
    }

    const matchEnd = matchIndex + searchTerm.length;
    parts.push(<mark className="search-hit" key={`${matchIndex}-${matchEnd}`}>{text.slice(matchIndex, matchEnd)}</mark>);
    cursor = matchEnd;
  }

  if (parts.length === 0) {
    return text;
  }

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts;
}

function getYearFromTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.getFullYear();
}

function getFileExtension(path: string) {
  const basename = getBasename(path);
  const extensionMatch = basename.match(/\.([^.]+)$/);
  return extensionMatch?.[1].toLowerCase() ?? '';
}

function getDisplayFileName(name: string) {
  return name.endsWith(bobsSceneSuffix) ? name.slice(0, -bobsSceneSuffix.length) : name;
}

function getPreviewKind(file: ManifestFile): PreviewKind | null {
  if (file.is_dir) {
    return null;
  }

  const extension = getFileExtension(file.path);
  if (imageExtensions.has(extension)) {
    return 'image';
  }

  if (generatedThumbnailExtensions.has(extension)) {
    return 'generated';
  }

  return null;
}

function isAbsoluteChildPath(path: string) {
  return path.startsWith('/') || path.startsWith('\\') || /^[A-Za-z]:([\\/]|$)/.test(path);
}

function hasParentTraversal(path: string) {
  return getPathSegments(path).some((segment) => segment === '..');
}

function getFilePreview(shipmentId: string, sourcePath: string, file: ManifestFile): FilePreview | null {
  const kind = getPreviewKind(file);
  const childPath = file.path.trim();
  if (!kind || sourcePath.trim() === '' || isAbsoluteChildPath(childPath) || hasParentTraversal(childPath)) {
    return null;
  }

  const absoluteSourcePath = sourcePath.trim().replace(/[\\/]+$/, '');
  const relativeFilePath = getPathSegments(childPath).join('/');
  if (absoluteSourcePath === '' || relativeFilePath === '') {
    return null;
  }

  return { kind, src: getGeneratedThumbnailUrl(shipmentId, absoluteSourcePath, relativeFilePath) };
}

function getDisplayPath(path: string) {
  const basename = getBasename(path);
  const displayFileName = getDisplayFileName(basename);
  const workTitle = getWorkTitle(path);
  return workTitle === basename || workTitle === displayFileName ? displayFileName : `${workTitle}/${displayFileName}`;
}

function formatFileSize(size: number) {
  if (size === 0) {
    return '0 MB';
  }

  const sizeInMb = size / (1024 * 1024);
  return `${sizeInMb.toFixed(sizeInMb >= 10 ? 1 : 2)} MB`;
}

function countFiles(files: ShipmentManifest['files']) {
  return files.filter((file) => !file.is_dir).length;
}

function isDescendantFile(folderPath: string, entryPath: string) {
  const folderSegments = getPathSegments(folderPath);
  const entrySegments = getPathSegments(entryPath);
  return folderSegments.length < entrySegments.length && folderSegments.every((segment, index) => segment === entrySegments[index]);
}

function countDescendantFiles(folder: ManifestFile, files: ShipmentManifest['files']) {
  return files.filter((entry) => !entry.is_dir && isDescendantFile(folder.path, entry.path)).length;
}

function createTreeNode(path: string, name: string, kind: TreeNodeKind, depth: number, file: ManifestFile | null): TreeNode {
  return {
    path,
    name,
    kind,
    depth,
    file,
    children: new Map(),
    descendantFileCount: 0,
  };
}

function getOrCreateFolderNode(parent: TreeNode, path: string, name: string, depth: number, file: ManifestFile | null) {
  const currentNode = parent.children.get(path);
  if (currentNode) {
    if (file && currentNode.file === null) {
      currentNode.file = file;
    }
    return currentNode;
  }

  const nextNode = createTreeNode(path, name, 'folder', depth, file);
  parent.children.set(path, nextNode);
  return nextNode;
}

function getPathFromSegments(segments: string[], endIndex: number) {
  return segments.slice(0, endIndex + 1).join('/');
}

function buildTreeRows(files: ShipmentManifest['files']): TreeRow[] {
  const root = createTreeNode('', '', 'folder', -1, null);

  files.forEach((file) => {
    const segments = getPathSegments(file.path);
    if (segments.length === 0) {
      return;
    }

    let parent = root;
    segments.forEach((segment, index) => {
      const isLeaf = index === segments.length - 1;
      const path = getPathFromSegments(segments, index);
      const depth = index;

      if (isLeaf && !file.is_dir) {
        parent.children.set(path, createTreeNode(path, segment, 'file', depth, file));
        return;
      }

      parent = getOrCreateFolderNode(parent, path, segment, depth, isLeaf ? file : null);
    });
  });

  function countNodeFiles(node: TreeNode): number {
    if (node.kind === 'file') {
      node.descendantFileCount = 1;
      return 1;
    }

    const descendantFileCount = Array.from(node.children.values()).reduce((total, child) => total + countNodeFiles(child), 0);
    node.descendantFileCount = descendantFileCount;
    return descendantFileCount;
  }

  countNodeFiles(root);

  const rows: TreeRow[] = [];
  function appendRows(node: TreeNode) {
    Array.from(node.children.values()).forEach((child) => {
      const file = child.file ?? { path: child.path, size: 0, is_dir: child.kind === 'folder' };
      rows.push({
        path: child.path,
        name: child.name,
        kind: child.kind,
        depth: child.depth,
        file,
        descendantFileCount: child.descendantFileCount,
        childFolderNames: Array.from(child.children.values()).filter((grandchild) => grandchild.kind === 'folder').map((grandchild) => grandchild.name),
        childFileNames: Array.from(child.children.values()).filter((grandchild) => grandchild.kind === 'file').map((grandchild) => grandchild.name),
        hasChildren: child.children.size > 0,
      });
      appendRows(child);
    });
  }

  appendRows(root);
  return rows;
}

function getAncestorFolderPaths(path: string) {
  const segments = getPathSegments(path);
  return segments.slice(0, -1).map((_, index) => getPathFromSegments(segments, index));
}

function isDateFolderName(name: string) {
  return /^(?:\d{4}_\d{4}|\d{4}_\d{2}\d{2}|\d{2}\d{2}_\d{4})$/.test(name);
}

function getDateFolderSummary(row: TreeRow) {
  if (row.kind !== 'folder' || !isDateFolderName(row.name) || row.childFolderNames.length === 0) {
    return '';
  }

  const visibleNames = row.childFolderNames.slice(0, 4);
  const hiddenCount = row.childFolderNames.length - visibleNames.length;
  return hiddenCount > 0 ? `${visibleNames.join(', ')} 외 ${hiddenCount}개` : visibleNames.join(', ');
}

function getVisibleTreeRows(rows: TreeRow[], collapsedFolderPaths: Set<string>) {
  return rows.filter((row) => !getAncestorFolderPaths(row.path).some((ancestorPath) => collapsedFolderPaths.has(ancestorPath)));
}

function getFolderInlineSummary(row: TreeRow) {
  const visibleChildNames = [...row.childFolderNames, ...row.childFileNames.map(getDisplayFileName)].slice(0, 3);
  const hiddenCount = row.childFolderNames.length + row.childFileNames.length - visibleChildNames.length;
  const childList = visibleChildNames.length > 0 ? ` · ${visibleChildNames.join(', ')}${hiddenCount > 0 ? ` 외 ${hiddenCount}개` : ''}` : '';
  return `폴더 안: 하위 폴더 ${row.childFolderNames.length}개 · 하위 파일 ${row.childFileNames.length}개${childList}`;
}

function getDateFromLabel(value: string, yearContext: number | null = null) {
  const yearFirstDate = value.match(/(?:^|_)(\d{4})_(\d{2})(\d{2})(?:_|$)/);
  if (yearFirstDate) {
    return `${yearFirstDate[1]}_${yearFirstDate[2]}${yearFirstDate[3]}`;
  }

  const yearLastDate = value.match(/(?:^|_)(\d{2})(\d{2})_(\d{4})(?:_|$)/);
  if (yearLastDate) {
    return `${yearLastDate[3]}_${yearLastDate[1]}${yearLastDate[2]}`;
  }

  const shortYearFirstDate = value.match(/^(\d{2})(\d{2})(\d{2})$/);
  if (shortYearFirstDate) {
    const baseYear = yearContext ?? new Date().getFullYear();
    const century = baseYear - (baseYear % 100);
    const year = century + Number(shortYearFirstDate[1]);
    const month = Number(shortYearFirstDate[2]);
    const day = Number(shortYearFirstDate[3]);
    const date = new Date(year, month - 1, day);
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
      return '';
    }
    return `${year}_${shortYearFirstDate[2]}${shortYearFirstDate[3]}`;
  }

  const bareDate = value.match(/^(\d{2})(\d{2})$/);
  if (!bareDate || yearContext === null) {
    return '';
  }

  const month = Number(bareDate[1]);
  const day = Number(bareDate[2]);
  const date = new Date(yearContext, month - 1, day);
  if (date.getFullYear() !== yearContext || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return '';
  }

  return `${yearContext}_${bareDate[0]}`;
}

function getDateFolderLabelFromPath(path: string, yearContext: number | null = null) {
  const segments = getPathSegments(path);
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const dateFolderLabel = getDateFromLabel(segments[index], yearContext);
    if (dateFolderLabel) {
      return dateFolderLabel;
    }
  }
  return getDateFromLabel(path, yearContext);
}

function getManifestDateFolderLabel(manifest: ShipmentManifest) {
  const yearContext = getYearFromTimestamp(manifest.created_at);
  const sources = [manifest.source_path, manifest.folder_name, ...manifest.files.map((file) => file.path)];
  for (const source of sources) {
    const dateFolderLabel = getDateFolderLabelFromPath(source, yearContext);
    if (dateFolderLabel) {
      return dateFolderLabel;
    }
  }
  return '';
}

export function ContentPanel({ manifest, searchQuery }: ContentPanelProps) {
  const [collapsedFolderPaths, setCollapsedFolderPaths] = useState<Set<string>>(() => new Set());
  const [hoveredFolderPath, setHoveredFolderPath] = useState('');
  const treeRows = useMemo(() => buildTreeRows(manifest?.files ?? []), [manifest?.files]);
  const visibleRows = useMemo(() => getVisibleTreeRows(treeRows, collapsedFolderPaths), [collapsedFolderPaths, treeRows]);

  useEffect(() => {
    setCollapsedFolderPaths(new Set());
    setHoveredFolderPath('');
  }, [manifest?.id]);

  if (!manifest) {
    return (
      <section className="content-panel empty-panel">
        <h2>선적 상세</h2>
        <p>왼쪽에서 선적 폴더를 선택하세요</p>
      </section>
    );
  }

  const sourceDateFolderLabel = getManifestDateFolderLabel(manifest);

  function toggleFolder(path: string) {
    setCollapsedFolderPaths((currentPaths) => {
      const nextPaths = new Set(currentPaths);
      if (nextPaths.has(path)) {
        nextPaths.delete(path);
      } else {
        nextPaths.add(path);
      }
      return nextPaths;
    });
  }

  return (
    <section className="content-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{new Date(manifest.created_at).toLocaleDateString('ko-KR')}</p>
          <h2 className={getWorkColorClassName(getManifestDisplayTitle(manifest))}>{renderHighlightedText(getManifestDisplayTitle(manifest), searchQuery)}</h2>
          {sourceDateFolderLabel && <p className="source-date-context">선적 날짜 <strong>{renderHighlightedText(sourceDateFolderLabel, searchQuery)}</strong></p>}
          <p>{renderHighlightedText(manifest.source_path, searchQuery)}</p>
        </div>
        <span>{renderHighlightedText(`${countFiles(manifest.files)}개 파일`, searchQuery)}</span>
      </div>
      {manifest.note && <p className="note">{renderHighlightedText(manifest.note, searchQuery)}</p>}
      <div className="file-list">
        {visibleRows.map((row) => {
          const file = row.file;
          const isFolder = row.kind === 'folder';
          const isExpanded = !collapsedFolderPaths.has(row.path);
          const displayPath = row.depth === 0 ? getDisplayPath(file.path) : isFolder ? row.name : getDisplayFileName(row.name);
          const preview = getFilePreview(manifest.id, manifest.source_path, file);
          const rowStyle: TreeRowStyle = { '--tree-depth': row.depth };
          const dateFolderSummary = getDateFolderSummary(row);
          const showInlineSummary = isFolder && hoveredFolderPath === row.path;
          const sceneValidation = !isFolder ? file.scene_validation : undefined;
          return (
            <div
              className={`file-row ${isFolder ? 'folder-row' : 'file-entry-row'} ${getWorkBackgroundClassName(file.path)}`}
              key={row.path}
              onBlur={() => {
                if (isFolder) {
                  setHoveredFolderPath('');
                }
              }}
              onMouseEnter={() => {
                if (isFolder) {
                  setHoveredFolderPath(row.path);
                }
              }}
              onMouseLeave={() => {
                if (isFolder) {
                  setHoveredFolderPath('');
                }
              }}
              style={rowStyle}
            >
              {isFolder ? (
                <button
                  aria-expanded={isExpanded}
                  aria-label={`${displayPath} 폴더 ${isExpanded ? '접기' : '펼치기'}`}
                  className="folder-toggle"
                  disabled={!row.hasChildren}
                  onFocus={() => setHoveredFolderPath(row.path)}
                  onClick={() => toggleFolder(row.path)}
                  type="button"
                >
                  <span className="folder-toggle-icon" aria-hidden="true">{row.hasChildren ? (isExpanded ? '▾' : '▸') : '•'}</span>
                  <span>{row.hasChildren ? (isExpanded ? '접기' : '펼치기') : '빈 폴더'}</span>
                </button>
              ) : (
                <span className="file-tree-spacer" aria-hidden="true">└</span>
              )}
              {preview?.kind === 'image' && (
                <img
                  alt={`${displayPath} 이미지 미리보기`}
                  className="file-preview"
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.hidden = true;
                  }}
                  src={preview.src}
                />
              )}
              {preview?.kind === 'generated' && (
                <img
                  alt={`${displayPath} 미리보기`}
                  className="file-preview"
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.hidden = true;
                  }}
                  src={preview.src}
                />
              )}
              {!preview && !isFolder && <span className="file-preview-placeholder" aria-hidden="true">파일</span>}
              <span className="file-kind" aria-label={isFolder ? '폴더' : '파일'}>{isFolder ? '▣ 폴더' : '문서 파일'}</span>
              <strong className={`file-path ${getWorkColorClassName(file.path)}`}>{renderHighlightedText(displayPath, searchQuery)}</strong>
              {dateFolderSummary && <span className="date-folder-summary">{renderHighlightedText(dateFolderSummary, searchQuery)}</span>}
              {showInlineSummary && <span className="folder-inline-summary" role="status">{renderHighlightedText(getFolderInlineSummary(row), searchQuery)}</span>}
              <em className="file-size">{renderHighlightedText(isFolder ? `파일 ${row.descendantFileCount || countDescendantFiles(file, manifest.files)}개` : formatFileSize(file.size), searchQuery)}</em>
              {sceneValidation && (
                <span
                  aria-label={sceneValidation.exists ? `씬 폴더 확인됨: ${sceneValidation.expected_folder_name}` : `씬 폴더 없음: ${sceneValidation.expected_folder_name}`}
                  className={`scene-validation-pill ${sceneValidation.exists ? 'scene-validation-pill-valid' : 'scene-validation-pill-missing'}`}
                  title={sceneValidation.exists ? sceneValidation.matched_path ?? sceneValidation.expected_folder_name : sceneValidation.reason}
                >
                  <span aria-hidden="true">{sceneValidation.exists ? '✓' : '×'}</span>
                  <span>{sceneValidation.exists ? '확인됨' : '없음'}</span>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
