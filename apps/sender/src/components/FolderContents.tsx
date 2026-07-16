import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { getGeneratedThumbnailUrl, type FileEntry } from '../api';

type FolderContentsProps = {
  backendBaseUrl: string;
  shipmentId: string;
  sourcePath: string;
  files: FileEntry[];
  defaultExpanded?: boolean;
  highlightQuery?: string;
};

const imageExtensions = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'avif', 'heic', 'heif']);
const generatedThumbnailExtensions = new Set(['mov', 'mp4', 'm4v', 'webm', 'psd', 'psb']);
const bobsSceneSuffix = '.bobs-scene';
const kingOfHillTitle = '킹오브더힐';
const floridaTitle = '플로리다';

type PreviewKind = 'image' | 'generated';

type FilePreview = {
  kind: PreviewKind;
  src: string;
};

type TreeNodeKind = 'folder' | 'file';

type TreeNode = {
  path: string;
  name: string;
  kind: TreeNodeKind;
  depth: number;
  file: FileEntry | null;
  children: Map<string, TreeNode>;
  descendantFileCount: number;
};

type TreeRow = {
  path: string;
  name: string;
  kind: TreeNodeKind;
  depth: number;
  file: FileEntry;
  descendantFileCount: number;
  childFolderNames: string[];
  childFileNames: string[];
  hasChildren: boolean;
};

type TreeRowStyle = CSSProperties & {
  '--tree-depth': number;
};

function getPathSegments(path: string) {
  return path.split(/[\\/]+/).filter(Boolean);
}

function getBasename(path: string) {
  const segments = getPathSegments(path);
  return segments[segments.length - 1] ?? path;
}

function getDisplayFileName(name: string) {
  return name.endsWith(bobsSceneSuffix) ? name.slice(0, -bobsSceneSuffix.length) : name;
}

function getFileExtension(path: string) {
  const basename = getBasename(path);
  const extensionMatch = basename.match(/\.([^.]+)$/);
  return extensionMatch?.[1].toLowerCase() ?? '';
}

function getPreviewKind(file: FileEntry): PreviewKind | null {
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

function getFilePreview(backendBaseUrl: string, shipmentId: string, sourcePath: string, file: FileEntry): FilePreview | null {
  const kind = getPreviewKind(file);
  const childPath = file.path.trim();
  const baseUrl = backendBaseUrl.trim();
  if (!kind || baseUrl === '' || sourcePath.trim() === '' || isAbsoluteChildPath(childPath) || hasParentTraversal(childPath)) {
    return null;
  }

  const absoluteSourcePath = sourcePath.trim().replace(/[\\/]+$/, '');
  const relativeFilePath = getPathSegments(childPath).join('/');
  if (absoluteSourcePath === '' || relativeFilePath === '') {
    return null;
  }

  return { kind, src: getGeneratedThumbnailUrl(baseUrl, shipmentId, absoluteSourcePath, relativeFilePath) };
}

function getHazbinEpisode(value: string) {
  return value.match(/HH_(\d+)(?=\D|$)/i)?.[1] ?? value.match(/HH0?(\d{3})(?=\D|$)/i)?.[1];
}

function getFloridaEpisode(value: string) {
  return value.match(/FL_(\d+)(?=\D|$)/i)?.[1] ?? value.match(/FL0?(\d{3})(?=\D|$)/i)?.[1];
}

function isFloridaValue(value: string) {
  return getPathSegments(value).some((segment) => /^FL/i.test(segment)) || /^FL/i.test(value);
}

function normalizeLooseSearchKey(value: string) {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9가-힣]+/gi, '')
    .replace(/hh0+(\d{3})/g, 'hh$1');
}

type SearchNeedle = {
  raw: string;
  literal: string;
  loose: string;
};

function getWorkTitle(path: string) {
  const segments = getPathSegments(path);
  const hazbinEpisode = segments.map(getHazbinEpisode).find((episode) => episode !== undefined);
  const floridaEpisode = segments.map(getFloridaEpisode).find((episode) => episode !== undefined);

  if (hazbinEpisode) {
    return `헤즈빈호텔 ${hazbinEpisode}화`;
  }

  if (floridaEpisode) {
    return `${floridaTitle} ${floridaEpisode}화`;
  }

  if (isFloridaValue(path)) {
    return floridaTitle;
  }

  if (segments.some((segment) => /^(?:bobs|bobs_burgers|fasa\d+)/i.test(segment))) {
    return '밥스버거';
  }

  if (segments.some((segment) => /^(15|16)/.test(segment))) {
    return kingOfHillTitle;
  }

  return segments[0] ?? path;
}

function getDisplayPath(path: string) {
  const workTitle = getWorkTitle(path);
  const basename = getDisplayFileName(getBasename(path));
  return workTitle === basename ? basename : `${workTitle}/${basename}`;
}

function formatFileSize(size: number) {
  if (size === 0) {
    return '0 MB';
  }

  const sizeInMb = size / (1024 * 1024);
  return `${sizeInMb.toFixed(sizeInMb >= 10 ? 1 : 2)} MB`;
}

function countDescendantFiles(folder: FileEntry, files: FileEntry[]) {
  return files.filter((entry) => !entry.is_dir && entry.path.startsWith(`${folder.path}/`)).length;
}

function createTreeNode(path: string, name: string, kind: TreeNodeKind, depth: number, file: FileEntry | null): TreeNode {
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

function getOrCreateFolderNode(parent: TreeNode, path: string, name: string, depth: number, file: FileEntry | null) {
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

function buildTreeRows(files: FileEntry[]): TreeRow[] {
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

function normalizeHighlightQuery(value: string) {
  const raw = value.trim();
  return {
    raw,
    literal: raw.toLocaleLowerCase(),
    loose: normalizeLooseSearchKey(raw),
  };
}

function searchValueMatches(value: string, searchNeedle: SearchNeedle) {
  return searchNeedle.raw !== '' && (
    value.toLocaleLowerCase().includes(searchNeedle.literal)
    || (searchNeedle.loose !== '' && normalizeLooseSearchKey(value).includes(searchNeedle.loose))
  );
}

function getTreeRowSearchValues(row: TreeRow) {
  return [row.name, row.path, row.file.path, getDisplayPath(row.file.path)];
}

function treeRowMatchesSearch(row: TreeRow, searchNeedle: SearchNeedle) {
  return getTreeRowSearchValues(row).some((value) => searchValueMatches(value, searchNeedle));
}

function getSearchContext(row: TreeRow, searchNeedle: SearchNeedle, displayPath: string) {
  if (searchNeedle.raw === '') {
    return '';
  }

  const matchingValue = [row.file.path, row.path, getDisplayPath(row.file.path), row.name]
    .find((value) => value !== displayPath && searchValueMatches(value, searchNeedle));
  return matchingValue ?? '';
}

function getSearchExpandedFolderPaths(rows: TreeRow[], searchNeedle: SearchNeedle) {
  const expandedPaths = new Set<string>();
  if (searchNeedle.raw === '') {
    return expandedPaths;
  }

  rows.forEach((row) => {
    if (!treeRowMatchesSearch(row, searchNeedle)) {
      return;
    }
    getAncestorFolderPaths(row.path).forEach((ancestorPath) => expandedPaths.add(ancestorPath));
  });

  return expandedPaths;
}

function getVisibleTreeRows(rows: TreeRow[], collapsedFolderPaths: Set<string>, searchExpandedFolderPaths: Set<string>) {
  return rows.filter((row) => !getAncestorFolderPaths(row.path).some((ancestorPath) => (
    collapsedFolderPaths.has(ancestorPath) && !searchExpandedFolderPaths.has(ancestorPath)
  )));
}

function renderHighlightedText(value: string, searchNeedle: SearchNeedle): ReactNode {
  if (searchNeedle.raw === '') {
    return value;
  }

  const normalizedValue = value.toLocaleLowerCase();
  const firstMatchIndex = normalizedValue.indexOf(searchNeedle.literal);
  if (firstMatchIndex === -1) {
    if (searchValueMatches(value, searchNeedle)) {
      return <mark className="search-highlight">{value}</mark>;
    }
    return value;
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;
  let matchIndex = firstMatchIndex;
  while (matchIndex !== -1) {
    if (matchIndex > cursor) {
      nodes.push(value.slice(cursor, matchIndex));
    }
    const matchEnd = matchIndex + searchNeedle.raw.length;
    nodes.push(<mark className="search-highlight" key={`${matchIndex}-${matchEnd}`}>{value.slice(matchIndex, matchEnd)}</mark>);
    cursor = matchEnd;
    matchIndex = normalizedValue.indexOf(searchNeedle.literal, cursor);
  }

  if (cursor < value.length) {
    nodes.push(value.slice(cursor));
  }

  return nodes;
}

function getCollapsedFolderPaths(rows: TreeRow[]) {
  return new Set(rows.filter((row) => row.kind === 'folder').map((row) => row.path));
}

function getFilesSignature(files: FileEntry[]) {
  return files
    .map((file) => `${file.path}\u0000${file.is_dir ? '1' : '0'}\u0000${file.size}`)
    .sort()
    .join('\u0001');
}

export function FolderContents({ backendBaseUrl, shipmentId, sourcePath, files, defaultExpanded = false, highlightQuery = '' }: FolderContentsProps) {
  const [collapsedFolderPaths, setCollapsedFolderPaths] = useState<Set<string>>(() => (defaultExpanded ? new Set() : getCollapsedFolderPaths(buildTreeRows(files))));
  const filesSignature = useMemo(() => getFilesSignature(files), [files]);
  const treeRows = useMemo(() => buildTreeRows(files), [files]);
  const normalizedHighlightQuery = useMemo(() => normalizeHighlightQuery(highlightQuery), [highlightQuery]);
  const searchExpandedFolderPaths = useMemo(() => getSearchExpandedFolderPaths(treeRows, normalizedHighlightQuery), [normalizedHighlightQuery, treeRows]);
  const visibleRows = useMemo(() => getVisibleTreeRows(treeRows, collapsedFolderPaths, searchExpandedFolderPaths), [collapsedFolderPaths, searchExpandedFolderPaths, treeRows]);

  useEffect(() => {
    setCollapsedFolderPaths(defaultExpanded ? new Set() : getCollapsedFolderPaths(treeRows));
  }, [defaultExpanded, filesSignature, sourcePath]);

  if (files.length === 0) {
    return <p className="empty">아직 표시할 파일이 없습니다.</p>;
  }

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
    <div className="file-list">
      {visibleRows.map((row) => {
        const file = row.file;
        const isFolder = row.kind === 'folder';
        const isExpanded = !collapsedFolderPaths.has(row.path) || searchExpandedFolderPaths.has(row.path);
        const isSearchMatch = treeRowMatchesSearch(row, normalizedHighlightQuery);
        const displayPath = row.depth === 0 ? getDisplayPath(file.path) : isFolder ? row.name : getDisplayFileName(row.name);
        const searchContext = isSearchMatch ? getSearchContext(row, normalizedHighlightQuery, displayPath) : '';
        const preview = getFilePreview(backendBaseUrl, shipmentId, sourcePath, file);
        const rowStyle: TreeRowStyle = { '--tree-depth': row.depth };
        const dateFolderSummary = getDateFolderSummary(row);
        return (
          <div
            className={`file-row ${isFolder ? 'folder-row' : 'file-entry-row'}${isSearchMatch ? ' search-match' : ''}`}
            key={row.path}
            style={rowStyle}
          >
            {isFolder ? (
              <button
                aria-expanded={isExpanded}
                aria-label={`${displayPath} 폴더 ${isExpanded ? '접기' : '펼치기'}`}
                className="folder-toggle"
                disabled={!row.hasChildren}
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
            <span className="file-text">
              <strong className="file-path">{renderHighlightedText(displayPath, normalizedHighlightQuery)}</strong>
              {searchContext && <span className="file-search-context">{renderHighlightedText(searchContext, normalizedHighlightQuery)}</span>}
            </span>
            {dateFolderSummary && <span className="date-folder-summary">{dateFolderSummary}</span>}
            <em className="file-size">{isFolder ? `파일 ${row.descendantFileCount || countDescendantFiles(file, files)}개` : formatFileSize(file.size)}</em>
          </div>
        );
      })}
    </div>
  );
}
