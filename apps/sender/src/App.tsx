import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { BobsCatalogJob, BobsRetakePdfParseResult, BobsRetakePdfRow, SenderHealth, ShipmentManifest } from './api';
import { fetchBobsCatalogJob, fetchBobsCatalogJobs, fetchSenderHealth, fetchSentHistory, getSenderBackendUrl, parseBobsRetakePdf, scanFolder, sendManifest } from './api';
import { listenForFolderDrops } from './dragDrop';
import { notify } from './notifications';
import { DropZone } from './components/DropZone';
import { EditPanel } from './components/EditPanel';
import { FolderContents } from './components/FolderContents';

const todayDate = new Date();
const currentYear = todayDate.getFullYear();
const todayDateFormatter = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'full' });
const yearOptions = Array.from({ length: 4 }, (_, index) => currentYear - 1 + index);
const monthOptions = Array.from({ length: 12 }, (_, index) => index + 1);
const sentTimestampFormatter = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});
const sentHistoryRetryDelays = [250, 750, 1500] as const;

const sentHistoryStorageKey = 'ship.sender.sentHistory.v1';
const bobsManifestSourcePrefix = 'bobs://';
const macosDataVolumePrefix = '/System/Volumes/Data';
const macosDataVolumeMatchKeyPrefix = 'macos-data-volume:';
const bobsSceneSuffix = '.bobs-scene';
const kingOfHillTitle = '킹오브더힐';
const floridaTitle = '플로리다';

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month, 0).getDate();
}

function padDatePart(value: number) {
  return value.toString().padStart(2, '0');
}

function formatTodayDateLabel() {
  return todayDateFormatter.format(new Date());
}

function getLocalDateKey(date: Date) {
  return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}`;
}

function isTimestampOnLocalDate(timestamp: string, localDateKey: string) {
  const date = new Date(timestamp);
  return !Number.isNaN(date.getTime()) && getLocalDateKey(date) === localDateKey;
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function isLikelyPdfPath(path: string) {
  return path.trim().toLocaleLowerCase().endsWith('.pdf');
}

function isLikelyExcelPath(path: string) {
  return /\.xlsx?$/.test(path.trim().toLocaleLowerCase());
}

function isLikelyBobsRetakePdfPath(path: string) {
  if (!isLikelyPdfPath(path)) {
    return false;
  }
  const normalizedPath = path.toLocaleLowerCase().replace(/[^a-z0-9가-힣]+/g, ' ');
  const compactPath = normalizedPath.replace(/\s+/g, '');
  return normalizedPath.includes('creative retakes')
    || normalizedPath.includes('technical retakes')
    || normalizedPath.includes('creatives')
    || compactPath.includes('creativeretakes')
    || compactPath.includes('technicalretakes')
    || (normalizedPath.includes('bobs') && normalizedPath.includes('retake'));
}

async function fetchSentHistoryWithRetry() {
  let lastError: unknown;
  for (let attempt = 0; attempt <= sentHistoryRetryDelays.length; attempt += 1) {
    try {
      return await fetchSentHistory();
    } catch (error) {
      lastError = error;
      const retryDelay = sentHistoryRetryDelays[attempt];
      if (retryDelay !== undefined) {
        await wait(retryDelay);
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error('이전 전송 기록을 불러오지 못했습니다.');
}

async function fetchSentHistoryAndHealth() {
  const [historyResult, healthResult] = await Promise.allSettled([
    fetchSentHistoryWithRetry(),
    fetchSenderHealth(),
  ]);

  return { historyResult, healthResult };
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message.trim() !== '') {
    return error.message;
  }

  return fallback;
}

function getSenderDbDiagnostic(senderHealth: SenderHealth | null, healthError: string) {
  if (senderHealth) {
    const dbPath = senderHealth.db.path.trim() || '경로 없음';
    const fileStatus = senderHealth.db.exists ? '파일 있음' : '파일 없음';
    const parentStatus = senderHealth.db.parent_exists ? '상위 폴더 있음' : '상위 폴더 없음';
    const dbError = senderHealth.db.error ? ` · DB 오류: ${senderHealth.db.error}` : '';
    const diagnostics = senderHealth.db.diagnostics?.length ? ` · 진단: ${senderHealth.db.diagnostics.join(' / ')}` : '';
    return `DB: ${dbPath} · ${fileStatus} · ${parentStatus} · 기록 ${senderHealth.db.history_count}개${dbError}${diagnostics}`;
  }

  if (healthError) {
    return `DB 상태 오류: ${healthError}`;
  }

  return 'DB 상태 확인 중';
}

function mergeSentHistory(sentManifests: ShipmentManifest[], currentHistory: ShipmentManifest[]) {
  const sentIds = new Set(sentManifests.map((manifest) => manifest.id));
  return [...sentManifests, ...currentHistory.filter((manifest) => !sentIds.has(manifest.id))];
}

function getNormalSendQueueSignature(manifests: ShipmentManifest[]) {
  return JSON.stringify(manifests.map((manifest) => ({
    id: manifest.id,
    source_path: manifest.source_path,
    folder_name: manifest.folder_name,
    created_at: manifest.created_at,
    files: manifest.files.map((file) => ({ path: file.path, size: file.size, is_dir: file.is_dir })),
  })));
}

function getNormalRevisionContentSignature(manifest: ShipmentManifest) {
  return JSON.stringify(manifest.files.map((file) => ({ path: file.path, size: file.size, is_dir: file.is_dir })));
}

function getMillisecondsUntilTomorrow() {
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setHours(24, 0, 0, 0);
  return tomorrow.getTime() - now.getTime();
}

function clearLegacySentHistory() {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.removeItem(sentHistoryStorageKey);
  } catch (error) {
    console.warn('이전 전송 기록 저장소를 정리하지 못했습니다.', error);
  }
}

function applySelectedDate(createdAt: string, year: number, month: number, day: number) {
  const selectedDate = `${year}-${padDatePart(month)}-${padDatePart(day)}`;
  if (/^\d{4}-\d{2}-\d{2}/.test(createdAt)) {
    return createdAt.replace(/^\d{4}-\d{2}-\d{2}/, selectedDate);
  }

  const fallback = new Date();
  fallback.setFullYear(year, month - 1, day);
  return fallback.toISOString();
}

function formatSentTimestamp(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return sentTimestampFormatter.format(date);
}

function getActualSentTimestamp(manifest: ShipmentManifest) {
  return manifest.sent_at ?? manifest.created_at;
}

function isBobsManifest(manifest: ShipmentManifest) {
  return manifest.source_path.startsWith(bobsManifestSourcePrefix);
}

function trimTrailingFolderSourceSeparators(sourcePath: string) {
  const trimmedPath = sourcePath.trim();
  let endIndex = trimmedPath.length;

  while (endIndex > 1 && /[\\/]/.test(trimmedPath[endIndex - 1])) {
    const nextPath = trimmedPath.slice(0, endIndex - 1);
    if (/^[A-Za-z]:$/.test(nextPath) || /^[\\/]+$/.test(nextPath)) {
      break;
    }
    endIndex -= 1;
  }

  return trimmedPath.slice(0, endIndex);
}

function isMacosDataVolumeAlias(volumeName: string) {
  const normalizedVolumeName = volumeName.toLocaleLowerCase();
  return normalizedVolumeName === 'data'
    || normalizedVolumeName === 'macintosh hd'
    || normalizedVolumeName === 'macintosh hd - data';
}

function normalizeFolderSourcePathForMatch(sourcePath: string) {
  const normalizedPath = trimTrailingFolderSourceSeparators(sourcePath);
  if (normalizedPath.startsWith(bobsManifestSourcePrefix)) {
    return normalizedPath;
  }

  if (normalizedPath === macosDataVolumePrefix) {
    return `${macosDataVolumeMatchKeyPrefix}/`;
  }
  if (normalizedPath.startsWith(`${macosDataVolumePrefix}/`)) {
    return `${macosDataVolumeMatchKeyPrefix}${normalizedPath.slice(macosDataVolumePrefix.length)}`;
  }

  const volumesPrefix = '/Volumes/';
  if (!normalizedPath.startsWith(volumesPrefix)) {
    return normalizedPath;
  }

  const volumeRelativePath = normalizedPath.slice(volumesPrefix.length);
  const firstSeparatorIndex = volumeRelativePath.indexOf('/');
  if (firstSeparatorIndex === -1) {
    return normalizedPath;
  }

  const volumeName = volumeRelativePath.slice(0, firstSeparatorIndex);
  if (!isMacosDataVolumeAlias(volumeName)) {
    return normalizedPath;
  }

  return `${macosDataVolumeMatchKeyPrefix}/${volumeRelativePath.slice(firstSeparatorIndex + 1)}`;
}

function getBobsTkLabelFromValue(value: string) {
  const tkDigits = sanitizeDigits(value.match(/\bTK\s*(\d+)\b/i)?.[1] ?? '');
  return tkDigits ? `TK${tkDigits}` : '';
}

function getBobsBatchLabelFromValue(value: string) {
  const batchDigits = sanitizeDigits(value.match(/\bbatch\s*(\d+)\b/i)?.[1] ?? '');
  return batchDigits ? `batch${batchDigits}` : '';
}

function getBobsTkNumberFromValue(value: string) {
  return sanitizeDigits(value.match(/\bTK\s*(\d+)\b/i)?.[1] ?? '');
}

function getBobsBatchNumberFromValue(value: string) {
  return sanitizeDigits(value.match(/\bbatch\s*(\d+)\b/i)?.[1] ?? '');
}

function getBobsTkLabelFromManifest(manifest: ShipmentManifest) {
  const sources = [manifest.folder_name, manifest.source_path, ...manifest.files.map((file) => file.path)];
  return sources.map(getBobsTkLabelFromValue).find((tkLabel) => tkLabel !== '') ?? '';
}

function getBobsCompactNumberFromManifest(manifest: ShipmentManifest) {
  const sources = [manifest.folder_name, manifest.source_path, ...manifest.files.map((file) => file.path)];
  return sources.map(getBobsTkNumberFromValue).find((tkNumber) => tkNumber !== '')
    ?? sources.map(getBobsBatchNumberFromValue).find((batchNumber) => batchNumber !== '')
    ?? '';
}

function insertBobsTkLabelInTitle(title: string, tkLabel: string) {
  const countSuffix = title.match(/\s+\d+개\s+(?:씬|파일)$/)?.[0] ?? '';
  if (countSuffix) {
    return `${title.slice(0, -countSuffix.length)} ${tkLabel}${countSuffix}`;
  }

  return `${title} ${tkLabel}`;
}

function getBobsManifestDisplayTitle(manifest: ShipmentManifest) {
  const title = manifest.folder_name.trim() || '밥스버거';
  if (getBobsBatchLabelFromValue(title) !== '') {
    return title;
  }

  const tkLabel = getBobsTkLabelFromManifest(manifest);
  if (tkLabel === '' || getBobsTkLabelFromValue(title) !== '') {
    return title;
  }

  return insertBobsTkLabelInTitle(title, tkLabel);
}

function removeBobsTkLabelsFromTitle(title: string) {
  return title.replace(/\s*\bTK\s*\d+\b/gi, '').replace(/\s{2,}/g, ' ').trim();
}

function removeBobsCountSuffixFromTitle(title: string) {
  return title.replace(/\s+\d+개\s+(?:씬|파일)$/, '').trim();
}

function getYearFromTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.getFullYear();
}

function getHazbinEpisode(value: string) {
  return value.match(/HH_(\d+)(?=\D|$)/i)?.[1] ?? value.match(/HH0?(\d{3})(?=\D|$)/i)?.[1];
}

function getFloridaEpisode(value: string) {
  return value.match(/FL_(\d+)(?=\D|$)/i)?.[1] ?? value.match(/FL0?(\d{3})(?=\D|$)/i)?.[1];
}

function getKothEpisode(value: string) {
  const match = value.match(/(?:^|[^A-Za-z0-9])((?:15|16)\d{2}(?:_PROMO)?)(?=$|[^A-Za-z0-9])/i);
  return match?.[1].toUpperCase();
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

type HistorySearchNeedle = {
  raw: string;
  literal: string;
  loose: string;
};

function getPathSegments(path: string) {
  return path.split(/[\\/]+/).filter(Boolean);
}

function getDisplayFolderName(folderName: string) {
  const segments = getPathSegments(folderName);
  const hazbinEpisode = segments.map(getHazbinEpisode).find((episode) => episode !== undefined) ?? getHazbinEpisode(folderName);
  const floridaEpisode = segments.map(getFloridaEpisode).find((episode) => episode !== undefined) ?? getFloridaEpisode(folderName);
  const kothEpisode = segments.map(getKothEpisode).find((episode) => episode !== undefined) ?? getKothEpisode(folderName);
  if (hazbinEpisode) {
    return `헤즈빈호텔 ${hazbinEpisode}화`;
  }
  if (floridaEpisode) {
    return `${floridaTitle} ${floridaEpisode}화`;
  }
  if (isFloridaValue(folderName)) {
    return floridaTitle;
  }
  if (segments.some((segment) => /^(?:bobs|bobs_burgers|fasa\d+)/i.test(segment)) || /^(?:bobs|bobs_burgers|fasa\d+)/i.test(folderName)) {
    return '밥스버거';
  }
  if (kothEpisode) {
    return `${kingOfHillTitle} ${kothEpisode}`;
  }
  if (segments.some((segment) => /^(15|16)/.test(segment)) || /^(15|16)/.test(folderName)) {
    return kingOfHillTitle;
  }
  return folderName;
}

function getWorkColorClassName(value: string) {
  const displayTitle = getDisplayFolderName(value);
  if (value.includes('헤즈빈호텔') || displayTitle.startsWith('헤즈빈호텔')) {
    return 'work-color-hazbin';
  }
  if (value.includes(floridaTitle) || displayTitle.startsWith(floridaTitle)) {
    return 'work-color-florida';
  }
  if (value.includes('밥스버거') || displayTitle.startsWith('밥스버거')) {
    return 'work-color-bobs';
  }
  if (value.includes(kingOfHillTitle) || displayTitle.startsWith(kingOfHillTitle)) {
    return 'work-color-koth';
  }
  return 'work-color-default';
}

function getWorkBackgroundClassName(value: string) {
  return getWorkColorClassName(value).replace('work-color-', 'work-bg-');
}

function getManifestWorkColorClassName(manifest: ShipmentManifest) {
  return getWorkColorClassName(getManifestDisplayTitle(manifest));
}

function getManifestWorkBackgroundClassName(manifest: ShipmentManifest) {
  return getWorkBackgroundClassName(getManifestDisplayTitle(manifest));
}

function getManifestDisplayTitles(manifest: ShipmentManifest) {
  if (isBobsManifest(manifest)) {
    return [getBobsManifestDisplayTitle(manifest)];
  }

  const sources = [manifest.folder_name, manifest.source_path, ...manifest.files.map((file) => file.path)];
  const mappedTitles = sources.map(getDisplayFolderName).filter((title, index) => title !== sources[index]);
  const uniqueTitles = Array.from(new Set(mappedTitles));
  const preferredTitle = uniqueTitles.find((title) => /^킹오브더힐 (?:15|16)/.test(title));
  return preferredTitle ? [preferredTitle, ...uniqueTitles.filter((title) => title !== preferredTitle)] : uniqueTitles.length > 0 ? uniqueTitles : [manifest.folder_name];
}

function getManifestDisplayTitle(manifest: ShipmentManifest) {
  return getManifestDisplayTitles(manifest)[0] ?? manifest.folder_name;
}

function countFiles(files: ShipmentManifest['files']) {
  return files.filter((file) => !file.is_dir).length;
}

type FolderDate = {
  year: number;
  month: number;
  day: number;
};

type SentHistoryDateParts = FolderDate & {
  time: number;
  dateTime: string;
  displayLabel: string;
  source: 'folderLabel' | 'createdAt';
};

type SentHistoryRow = {
  manifest: ShipmentManifest;
  index: number;
  dateParts: SentHistoryDateParts | null;
};

type SenderMode = 'transfer' | 'bobs';

type BobsSelectionMode = 'SEQ' | 'scene';

type ShipmentDateSortOrder = 'newest' | 'oldest';

function isValidFolderDate(year: number, month: number, day: number) {
  const folderDate = new Date(year, month - 1, day);
  return folderDate.getFullYear() === year && folderDate.getMonth() === month - 1 && folderDate.getDate() === day;
}

function createFolderDate(year: number, month: number, day: number): FolderDate | null {
  return isValidFolderDate(year, month, day) ? { year, month, day } : null;
}

function getDateFromTimestampPrefix(value: string): FolderDate | null {
  const dateMatch = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:T|$)/);
  if (!dateMatch) {
    return null;
  }

  return createFolderDate(Number(dateMatch[1]), Number(dateMatch[2]), Number(dateMatch[3]));
}

function getDateFromLabel(value: string, yearContext: number | null = null): FolderDate | null {
  const yearFirstMatch = value.match(/(?:^|_)(\d{4})_(\d{2})(\d{2})(?:_|$)/);
  if (yearFirstMatch) {
    const folderDate = createFolderDate(Number(yearFirstMatch[1]), Number(yearFirstMatch[2]), Number(yearFirstMatch[3]));
    if (folderDate) {
      return folderDate;
    }
  }

  const yearLastMatch = value.match(/(?:^|_)(\d{2})(\d{2})_(\d{4})(?:_|$)/);
  if (yearLastMatch) {
    return createFolderDate(Number(yearLastMatch[3]), Number(yearLastMatch[1]), Number(yearLastMatch[2]));
  }

  const shortYearFirstMatch = value.match(/^(\d{2})(\d{2})(\d{2})$/);
  if (shortYearFirstMatch) {
    const baseYear = yearContext ?? currentYear;
    const century = baseYear - (baseYear % 100);
    return createFolderDate(century + Number(shortYearFirstMatch[1]), Number(shortYearFirstMatch[2]), Number(shortYearFirstMatch[3]));
  }

  const bareDateMatch = value.match(/^(\d{2})(\d{2})$/);
  if (bareDateMatch && yearContext !== null) {
    return createFolderDate(yearContext, Number(bareDateMatch[1]), Number(bareDateMatch[2]));
  }

  return null;
}

function getDateLabelFromLabel(value: string, yearContext: number | null = null) {
  const folderDate = getDateFromLabel(value, yearContext);
  if (!folderDate) {
    return '';
  }

  return `${folderDate.year}_${padDatePart(folderDate.month)}${padDatePart(folderDate.day)}`;
}

function getDateFromPath(path: string, yearContext: number | null = null): FolderDate | null {
  const segments = path.split(/[\\/]+/).filter(Boolean);

  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const segmentDate = getDateFromLabel(segments[index], yearContext);
    if (segmentDate) {
      return segmentDate;
    }
  }

  return getDateFromLabel(path, yearContext);
}

function getDateFromManifestLabels(manifest: ShipmentManifest): FolderDate | null {
  const yearContext = getYearFromTimestamp(manifest.created_at);
  const sources = [manifest.folder_name, manifest.source_path, ...manifest.files.map((file) => file.path)];
  for (const source of sources) {
    const sourceDate = getDateFromPath(source, yearContext);
    if (sourceDate) {
      return sourceDate;
    }
  }
  return null;
}

function getDateFolderLabelFromPath(path: string, yearContext: number | null = null) {
  const segments = getPathSegments(path);
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const dateFolderLabel = getDateLabelFromLabel(segments[index], yearContext);
    if (dateFolderLabel) {
      return dateFolderLabel;
    }
  }
  return getDateLabelFromLabel(path, yearContext);
}

function getManifestDateFolderLabel(manifest: ShipmentManifest, yearContext = getYearFromTimestamp(manifest.created_at)) {
  const sources = [manifest.source_path, manifest.folder_name, ...manifest.files.map((file) => file.path)];
  for (const source of sources) {
    const dateFolderLabel = getDateFolderLabelFromPath(source, yearContext);
    if (dateFolderLabel) {
      return dateFolderLabel;
    }
  }
  if (isBobsManifest(manifest)) {
    const createdDatePrefix = getDateFromTimestampPrefix(manifest.created_at);
    if (createdDatePrefix) {
      return `${createdDatePrefix.year}_${padDatePart(createdDatePrefix.month)}${padDatePart(createdDatePrefix.day)}`;
    }

    const date = new Date(manifest.created_at);
    if (!Number.isNaN(date.getTime())) {
      return `${date.getFullYear()}_${padDatePart(date.getMonth() + 1)}${padDatePart(date.getDate())}`;
    }
  }
  return '';
}

function getNormalRevisionMatchKey(manifest: ShipmentManifest, yearContext: number | null = getYearFromTimestamp(manifest.created_at)) {
  const dateLabel = getManifestDateFolderLabel(manifest, yearContext);
  const displayTitle = getManifestDisplayTitle(manifest);
  if (dateLabel === '' || displayTitle.trim() === '') {
    return null;
  }
  return `${dateLabel}\u0000${displayTitle}`;
}

function findChangedNormalRevisionSourceManifest(replacementManifest: ShipmentManifest, sentManifests: ShipmentManifest[], yearContext: number | null) {
  const replacementKey = getNormalRevisionMatchKey(replacementManifest, yearContext);
  if (replacementKey === null) {
    return null;
  }
  const replacementContentSignature = getNormalRevisionContentSignature(replacementManifest);
  return sentManifests.find((manifest) => (
    !isBobsManifest(manifest)
    && getNormalRevisionMatchKey(manifest, yearContext) === replacementKey
    && getNormalRevisionContentSignature(manifest) !== replacementContentSignature
  )) ?? null;
}

function formatFolderDateLabel(folderDate: FolderDate) {
  return `${folderDate.year}년 ${folderDate.month}월 ${folderDate.day}일`;
}

function getSentHistoryDateParts(manifest: ShipmentManifest): SentHistoryDateParts | null {
  const folderDate = getDateFromManifestLabels(manifest);
  if (folderDate) {
    const date = new Date(folderDate.year, folderDate.month - 1, folderDate.day);
    return {
      ...folderDate,
      time: date.getTime(),
      dateTime: `${folderDate.year}-${padDatePart(folderDate.month)}-${padDatePart(folderDate.day)}`,
      displayLabel: formatFolderDateLabel(folderDate),
      source: 'folderLabel',
    };
  }

  const sentDate = new Date(manifest.created_at);
  const time = sentDate.getTime();
  if (Number.isNaN(time)) {
    return null;
  }

  return {
    year: sentDate.getFullYear(),
    month: sentDate.getMonth() + 1,
    day: sentDate.getDate(),
    time,
    dateTime: manifest.created_at,
    displayLabel: formatSentTimestamp(manifest.created_at),
    source: 'createdAt',
  };
}

function normalizeHistorySearchQuery(value: string) {
  const raw = value.trim();
  return {
    raw,
    literal: raw.toLocaleLowerCase(),
    loose: normalizeLooseSearchKey(raw),
  };
}

function textMatchesHistorySearch(value: string, searchNeedle: HistorySearchNeedle) {
  return searchNeedle.raw === ''
    || value.toLocaleLowerCase().includes(searchNeedle.literal)
    || (searchNeedle.loose !== '' && normalizeLooseSearchKey(value).includes(searchNeedle.loose));
}

function getManifestSearchValues(manifest: ShipmentManifest) {
  return [
    ...getManifestDisplayTitles(manifest),
    manifest.folder_name,
    manifest.source_path,
    ...manifest.files.map((file) => file.path),
  ];
}

function historyRowMatchesSearch(row: SentHistoryRow, searchNeedle: HistorySearchNeedle) {
  return searchNeedle.raw === '' || getManifestSearchValues(row.manifest).some((value) => textMatchesHistorySearch(value, searchNeedle));
}

function renderSearchHighlightedText(value: string, query: string): ReactNode {
  const trimmedQuery = query.trim();
  if (trimmedQuery === '') {
    return value;
  }

  const normalizedValue = value.toLocaleLowerCase();
  const normalizedQuery = trimmedQuery.toLocaleLowerCase();
  const firstMatchIndex = normalizedValue.indexOf(normalizedQuery);
  if (firstMatchIndex === -1) {
    return value;
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;
  let matchIndex = firstMatchIndex;
  while (matchIndex !== -1) {
    if (matchIndex > cursor) {
      nodes.push(value.slice(cursor, matchIndex));
    }
    const matchEnd = matchIndex + trimmedQuery.length;
    nodes.push(<mark className="search-highlight" key={`${matchIndex}-${matchEnd}`}>{value.slice(matchIndex, matchEnd)}</mark>);
    cursor = matchEnd;
    matchIndex = normalizedValue.indexOf(normalizedQuery, cursor);
  }

  if (cursor < value.length) {
    nodes.push(value.slice(cursor));
  }

  return nodes;
}

function getSelectedHistoryFilter(value: string) {
  return value === 'all' ? null : Number(value);
}

function getHistoryDateOptions(rows: SentHistoryRow[], selectValue: (row: SentHistoryRow) => number | null) {
  const counts = new Map<number, number>();
  rows.forEach((row) => {
    const value = selectValue(row);
    if (value !== null) {
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
  });

  return Array.from(counts, ([value, count]) => ({ value, count })).sort((left, right) => right.value - left.value);
}

function compareHistoryRowsByShipmentDate(left: SentHistoryRow, right: SentHistoryRow, sortOrder: ShipmentDateSortOrder) {
  if (left.dateParts && right.dateParts && left.dateParts.time !== right.dateParts.time) {
    return sortOrder === 'newest'
      ? right.dateParts.time - left.dateParts.time
      : left.dateParts.time - right.dateParts.time;
  }
  if (left.dateParts && !right.dateParts) {
    return -1;
  }
  if (!left.dateParts && right.dateParts) {
    return 1;
  }

  return sortOrder === 'newest' ? right.index - left.index : left.index - right.index;
}

function getUniqueBobsSceneEntries(sceneEntries: BobsSelectedScene[]) {
  const seenScenes = new Set<string>();
  return sceneEntries.filter((sceneEntry) => {
    const sceneKey = getBobsManifestSceneName(sceneEntry);
    if (seenScenes.has(sceneKey)) {
      return false;
    }
    seenScenes.add(sceneKey);
    return true;
  });
}

function getSortedBobsSceneEntries(sceneEntries: BobsSelectedScene[]) {
  return [...sceneEntries].sort((left, right) => compareNaturalBobsSequenceKeys(getBobsManifestSceneName(left), getBobsManifestSceneName(right)));
}

function sanitizeDigits(value: string) {
  return value.replace(/\D/g, '');
}

function getBobsManifestSceneName(sceneEntry: BobsSelectedScene) {
  return sceneEntry.displayScene ?? sceneEntry.scene;
}

function getBobsManifestFilePath(job: string, scene: string, tkSegment: string, includeTkFolder: boolean) {
  const pathParts = [job, includeTkFolder && tkSegment ? tkSegment : '', `${scene}.bobs-scene`].filter(Boolean);
  return pathParts.join('/');
}

function createBobsBatchManifest(
  sceneEntries: BobsSelectedScene[],
  batchOrTkNumber: string,
  selectedDate: FolderDate,
  includeTkFolder = false,
  labelKind: 'TK' | 'batch' = 'TK',
  shipmentKind: 'batch' | 'retake' = 'batch',
): ShipmentManifest | null {
  const uniqueSceneEntries = getSortedBobsSceneEntries(getUniqueBobsSceneEntries(sceneEntries));
  const firstSceneEntry = uniqueSceneEntries[0];
  if (!firstSceneEntry) {
    return null;
  }

  const jobDetail = firstSceneEntry.jobDetail;
  const scenes = uniqueSceneEntries.map(getBobsManifestSceneName);
  const sceneKey = scenes.join('+');
  const labelDigits = sanitizeDigits(batchOrTkNumber);
  const labelSegment = labelDigits ? `${labelKind}${labelDigits}` : '';
  const tkSegment = labelKind === 'TK' ? labelSegment : '';
  const titleParts = ['밥스버거', jobDetail.job, labelSegment, `${scenes.length}개 씬`].filter(Boolean);
  const batchKey = labelSegment ? `${labelSegment}/${sceneKey}` : sceneKey;
  const sourcePath = `bobs://${jobDetail.environment}/${jobDetail.job}/${shipmentKind}/${batchKey}`;
  return {
    id: `bobs:${jobDetail.environment}:${jobDetail.job}:${shipmentKind}:${batchKey}`,
    source_path: sourcePath,
    folder_name: titleParts.join(' '),
    created_at: applySelectedDate(new Date().toISOString(), selectedDate.year, selectedDate.month, selectedDate.day),
    note: '',
    files: scenes.map((scene) => ({ path: getBobsManifestFilePath(jobDetail.job, scene, tkSegment, includeTkFolder), size: 0, is_dir: false })),
  };
}

function createBobsRevisionManifest(generatedManifest: ShipmentManifest, originalManifest: ShipmentManifest): ShipmentManifest {
  return createRevisionReplacementManifest(generatedManifest, originalManifest);
}

function createRevisionReplacementManifest(replacementManifest: ShipmentManifest, originalManifest: ShipmentManifest): ShipmentManifest {
  return {
    ...replacementManifest,
    id: originalManifest.id,
  };
}

function getManifestQueueSignature(manifest: ShipmentManifest) {
  const fileSignature = manifest.files.map((file) => `${file.is_dir ? 'dir' : 'file'}:${file.path}:${file.size}`).join('|');
  return `${manifest.id}\u0000${manifest.source_path}\u0000${manifest.folder_name}\u0000${manifest.created_at}\u0000${fileSignature}`;
}

function areManifestQueuesEqual(left: ShipmentManifest[], right: ShipmentManifest[]) {
  return left.length === right.length && left.every((manifest, index) => getManifestQueueSignature(manifest) === getManifestQueueSignature(right[index]));
}

function getUserVisibleBobsWarnings(warnings: string[]) {
  const expectedFallbackWarningPrefixes = [
    'jobs.db is not readable SQLite:',
    'jobs.db scanned as custom binary data',
    'jobs.db custom binary scan found',
    'scene.db is not readable SQLite:',
    'scene.db scanned as custom binary data',
    'scene.db custom binary scan found',
  ];

  return warnings.filter((warning) => !expectedFallbackWarningPrefixes.some((prefix) => warning.trim().startsWith(prefix)));
}

function getBobsWarningsMessage(warnings: string[]) {
  const visibleWarnings = getUserVisibleBobsWarnings(warnings);
  return visibleWarnings.length > 0 ? visibleWarnings.join(' · ') : '';
}

type BobsSelectedScene = {
  jobDetail: BobsCatalogJob;
  scene: string;
  displayScene?: string;
};

type PendingBobsRetakePdf = {
  sourcePath: string;
  job: string;
  rows: BobsRetakePdfRow[];
};

type BobsRetakePdfMatchedRow = {
  sequence: string;
  sceneNumber: string;
  sceneLabel: string;
  tk: string;
  scene: string;
  displayScene: string;
};

type BobsRetakePdfSelection = {
  sourcePath: string;
  job: string;
  rows: BobsRetakePdfMatchedRow[];
};

type BobsHistorySelection = {
  manifestId: string;
  job: string;
  tkNumber: string;
  scenes: string[];
};

type BobsRangeAnchor = {
  job: string;
  value: string;
};

type NaturalBobsSequencePart =
  | { kind: 'number'; value: number; raw: string }
  | { kind: 'text'; value: string };

const naturalBobsSequencePartPattern = /\d+|\D+/g;

function getNaturalBobsSequenceParts(value: string): NaturalBobsSequencePart[] {
  return (value.match(naturalBobsSequencePartPattern) ?? [value]).map((part) => {
    if (/^\d+$/.test(part)) {
      return { kind: 'number', value: Number(part), raw: part };
    }

    return { kind: 'text', value: part.toLocaleLowerCase() };
  });
}

function compareNaturalBobsSequenceKeys(left: string, right: string) {
  const leftParts = getNaturalBobsSequenceParts(left);
  const rightParts = getNaturalBobsSequenceParts(right);
  const partCount = Math.max(leftParts.length, rightParts.length);

  for (let index = 0; index < partCount; index += 1) {
    const leftPart = leftParts[index];
    const rightPart = rightParts[index];
    if (!leftPart) {
      return -1;
    }
    if (!rightPart) {
      return 1;
    }
    if (leftPart.kind !== rightPart.kind) {
      return leftPart.kind === 'number' ? -1 : 1;
    }
    if (leftPart.kind === 'number' && rightPart.kind === 'number') {
      if (leftPart.value !== rightPart.value) {
        return leftPart.value - rightPart.value;
      }
      if (leftPart.raw.length !== rightPart.raw.length) {
        return leftPart.raw.length - rightPart.raw.length;
      }
      const rawOrder = leftPart.raw.localeCompare(rightPart.raw);
      if (rawOrder !== 0) {
        return rawOrder;
      }
      continue;
    }

    if (leftPart.kind === 'text' && rightPart.kind === 'text') {
      const textOrder = leftPart.value.localeCompare(rightPart.value);
      if (textOrder !== 0) {
        return textOrder;
      }
    }
  }

  return left.localeCompare(right);
}

function getSortedBobsSequenceKeys(sequences: BobsCatalogJob['sequences']) {
  return Object.keys(sequences).sort(compareNaturalBobsSequenceKeys);
}

function toggleSelection(values: string[], value: string) {
  return values.includes(value) ? values.filter((currentValue) => currentValue !== value) : [...values, value];
}

function addRangeSelection(values: string[], visibleValues: string[], anchorValue: string, targetValue: string) {
  const anchorIndex = visibleValues.indexOf(anchorValue);
  const targetIndex = visibleValues.indexOf(targetValue);
  if (anchorIndex === -1 || targetIndex === -1) {
    return toggleSelection(values, targetValue);
  }

  const rangeStart = Math.min(anchorIndex, targetIndex);
  const rangeEnd = Math.max(anchorIndex, targetIndex);
  const selectedValues = new Set(values);
  visibleValues.slice(rangeStart, rangeEnd + 1).forEach((value) => selectedValues.add(value));
  return Array.from(selectedValues);
}

function getSelectedJobValues(valuesByJob: Record<string, string[]>, job: string) {
  return valuesByJob[job] ?? [];
}

function isCurrentBobsJob(job: string) {
  if (/^GASA/i.test(job)) {
    return true;
  }

  const fasaMatch = job.match(/^FASA(\d+)$/i);
  return fasaMatch !== null && Number(fasaMatch[1]) >= 1;
}

function getCurrentBobsJobs(jobs: string[]) {
  return jobs.filter(isCurrentBobsJob);
}

function getBobsJobFromTitle(value: string) {
  return value.match(/\b(FASA\d+)\b/i)?.[1]?.toUpperCase() ?? null;
}

function getBobsJobFromSourcePath(sourcePath: string) {
  if (!sourcePath.startsWith(bobsManifestSourcePrefix)) {
    return null;
  }

  const segments = getPathSegments(sourcePath.slice(bobsManifestSourcePrefix.length));
  const fasaSegment = segments.find((segment) => /^FASA\d+$/i.test(segment));
  return fasaSegment?.toUpperCase() ?? segments[1] ?? null;
}

function getBobsJobFromFilePath(filePath: string) {
  const fasaSegment = getPathSegments(filePath).find((segment) => /^FASA\d+$/i.test(segment));
  return fasaSegment?.toUpperCase() ?? null;
}

function getBobsJobFromManifest(manifest: ShipmentManifest) {
  return getBobsJobFromSourcePath(manifest.source_path)
    ?? manifest.files.map((file) => getBobsJobFromFilePath(file.path)).find((job) => job !== null)
    ?? getBobsJobFromTitle(manifest.folder_name);
}

function stripBobsSceneSuffix(value: string) {
  return value.endsWith(bobsSceneSuffix) ? value.slice(0, -bobsSceneSuffix.length) : value;
}

function getBobsSceneFromFilePath(filePath: string) {
  const segments = getPathSegments(filePath);
  const basename = segments[segments.length - 1] ?? filePath;
  const scene = stripBobsSceneSuffix(basename).trim();
  return scene === '' ? null : scene;
}

function getBobsScenesFromManifest(manifest: ShipmentManifest) {
  const seenScenes = new Set<string>();
  const scenes: string[] = [];
  manifest.files.forEach((file) => {
    if (file.is_dir) {
      return;
    }

    const scene = getBobsSceneFromFilePath(file.path);
    if (scene && !seenScenes.has(scene)) {
      seenScenes.add(scene);
      scenes.push(scene);
    }
  });
  return scenes;
}

function getBobsHistorySelection(manifest: ShipmentManifest): BobsHistorySelection | null {
  if (!isBobsManifest(manifest)) {
    return null;
  }

  const job = getBobsJobFromManifest(manifest);
  if (!job) {
    return null;
  }

  return {
    manifestId: manifest.id,
    job,
    tkNumber: getBobsCompactNumberFromManifest(manifest),
    scenes: getBobsScenesFromManifest(manifest),
  };
}

function areStringArraysEqual(left: string[], right: string[]) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function replaceSelectedJobValues(valuesByJob: Record<string, string[]>, job: string, values: string[]) {
  return areStringArraysEqual(getSelectedJobValues(valuesByJob, job), values) ? valuesByJob : { ...valuesByJob, [job]: values };
}

function getRepresentingBobsSequences(jobDetail: BobsCatalogJob, scenes: string[]) {
  const selectedSceneSet = new Set(scenes);
  const sequences = Object.entries(jobDetail.sequences)
    .filter(([, sequenceScenes]) => sequenceScenes.length > 0 && sequenceScenes.every((scene) => selectedSceneSet.has(scene)))
    .map(([sequence]) => sequence);
  const representedScenes = new Set(sequences.flatMap((sequence) => jobDetail.sequences[sequence] ?? []));
  const representsEverySelectedScene = scenes.every((scene) => representedScenes.has(scene));
  return representsEverySelectedScene && representedScenes.size === selectedSceneSet.size ? sequences : [];
}

function getUniqueValues(values: string[]) {
  return Array.from(new Set(values));
}

function getBobsSceneParts(scene: string) {
  const match = scene.match(/^(.+)_S(\d{2})([A-Za-z]*)$/);
  if (!match) {
    return null;
  }
  return { sequence: match[1].toUpperCase(), sceneNumber: match[2], sceneLabel: `${match[2]}${match[3] ?? ''}` };
}

function getBobsCatalogSceneFromDisplayScene(scene: string) {
  const sceneParts = getBobsSceneParts(scene);
  return sceneParts ? `${sceneParts.sequence}_S${sceneParts.sceneNumber}` : scene;
}

function bobsSceneMatchesRetakeRow(scene: string, row: BobsRetakePdfRow) {
  const sceneParts = getBobsSceneParts(scene);
  if (!sceneParts || sceneParts.sceneNumber !== row.scene_number) {
    return false;
  }
  const parsedSequence = row.sequence.toUpperCase();
  if (sceneParts.sequence === parsedSequence) {
    return true;
  }
  return /^\d+$/.test(parsedSequence)
    && sceneParts.sequence.startsWith(parsedSequence)
    && !/^\d$/.test(sceneParts.sequence.charAt(parsedSequence.length));
}

function getBobsRetakeDisplayScene(row: BobsRetakePdfRow) {
  const sequence = row.sequence.trim().toUpperCase();
  const sceneLabel = (row.scene_label.trim() || row.scene_number).toUpperCase();
  return `${sequence}_S${sceneLabel}`;
}

function getMatchedBobsRetakeRows(jobDetail: BobsCatalogJob, rows: BobsRetakePdfRow[]) {
  const matchedRows: BobsRetakePdfMatchedRow[] = [];
  const seenRows = new Set<string>();
  rows.forEach((row) => {
    jobDetail.scenes.filter((scene) => bobsSceneMatchesRetakeRow(scene, row)).forEach((scene) => {
      const displayScene = getBobsRetakeDisplayScene(row);
      const rowKey = `${row.tk}\u0000${scene}\u0000${displayScene}`;
      if (seenRows.has(rowKey)) {
        return;
      }
      seenRows.add(rowKey);
      matchedRows.push({ sequence: row.sequence, sceneNumber: row.scene_number, sceneLabel: row.scene_label, tk: row.tk, scene, displayScene });
    });
  });
  return matchedRows;
}

function createBobsRetakePdfManifests(pdfSelection: BobsRetakePdfSelection, jobDetail: BobsCatalogJob, selectedDate: FolderDate) {
  const rowsByTk = new Map<string, BobsSelectedScene[]>();
  pdfSelection.rows.forEach((row) => {
    const entries = rowsByTk.get(row.tk) ?? [];
    entries.push({ jobDetail, scene: row.scene, displayScene: row.displayScene });
    rowsByTk.set(row.tk, entries);
  });
  return Array.from(rowsByTk.entries())
    .sort(([leftTk], [rightTk]) => leftTk.localeCompare(rightTk))
    .map(([tk, sceneEntries]) => createBobsBatchManifest(sceneEntries, tk, selectedDate, true, 'TK', 'retake'))
    .filter((manifest): manifest is ShipmentManifest => manifest !== null);
}

function createBobsRetakeReviewManifest(manifests: ShipmentManifest[]): ShipmentManifest | null {
  const firstManifest = manifests[0];
  if (!firstManifest) {
    return null;
  }

  const files = manifests.flatMap((manifest) => manifest.files);
  const tkLabels = manifests
    .map(getBobsTkLabelFromManifest)
    .filter((label) => label !== '');
  const titleBase = removeBobsCountSuffixFromTitle(removeBobsTkLabelsFromTitle(getManifestDisplayTitle(firstManifest)));
  const titleParts = [titleBase, tkLabels.length > 0 ? getUniqueValues(tkLabels).join('+') : '', `${countFiles(files)}개 파일`].filter(Boolean);
  return {
    ...firstManifest,
    id: `${firstManifest.id}:review`,
    folder_name: titleParts.join(' '),
    files,
  };
}

export default function App() {
  const [manifests, setManifests] = useState<ShipmentManifest[]>([]);
  const [activeReviewManifest, setActiveReviewManifest] = useState<ShipmentManifest | null>(null);
  const [sentHistory, setSentHistory] = useState<ShipmentManifest[]>([]);
  const [activeManifestId, setActiveManifestId] = useState<string | null>(null);
  const [activeHistoryManifestId, setActiveHistoryManifestIdState] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedMonth, setSelectedMonth] = useState(todayDate.getMonth() + 1);
  const [selectedDay, setSelectedDay] = useState(todayDate.getDate());
  const [historyYearFilter, setHistoryYearFilter] = useState('all');
  const [historyMonthFilter, setHistoryMonthFilter] = useState('all');
  const [historyDayFilter, setHistoryDayFilter] = useState('all');
  const [historySearchQuery, setHistorySearchQuery] = useState('');
  const [shipmentDateSortOrder, setShipmentDateSortOrder] = useState<ShipmentDateSortOrder>('newest');
  const [status, setStatus] = useState('');
  const [senderHealth, setSenderHealth] = useState<SenderHealth | null>(null);
  const [senderHealthError, setSenderHealthError] = useState('');
  const [senderBackendUrl, setSenderBackendUrl] = useState('');
  const [historyLoadError, setHistoryLoadError] = useState('');
  const [senderMode, setSenderMode] = useState<SenderMode>('transfer');
  const [bobsJobs, setBobsJobs] = useState<string[]>([]);
  const [bobsJobWarnings, setBobsJobWarnings] = useState<string[]>([]);
  const [bobsJobsError, setBobsJobsError] = useState('');
  const [selectedBobsJob, setSelectedBobsJob] = useState<string | null>(null);
  const [bobsJobDetailCache, setBobsJobDetailCache] = useState<Record<string, BobsCatalogJob>>({});
  const [bobsJobDetailErrors, setBobsJobDetailErrors] = useState<Record<string, string>>({});
  const [bobsSelectionMode, setBobsSelectionMode] = useState<BobsSelectionMode>('SEQ');
  const [bobsTkNumber, setBobsTkNumber] = useState('');
  const [selectedBobsSequencesByJob, setSelectedBobsSequencesByJob] = useState<Record<string, string[]>>({});
  const [selectedBobsScenesByJob, setSelectedBobsScenesByJob] = useState<Record<string, string[]>>({});
  const [pendingBobsRetakePdf, setPendingBobsRetakePdf] = useState<PendingBobsRetakePdf | null>(null);
  const [activeBobsRetakePdfSelection, setActiveBobsRetakePdfSelection] = useState<BobsRetakePdfSelection | null>(null);
  const [lastBobsSequenceRangeAnchor, setLastBobsSequenceRangeAnchor] = useState<BobsRangeAnchor | null>(null);
  const [lastBobsSceneRangeAnchor, setLastBobsSceneRangeAnchor] = useState<BobsRangeAnchor | null>(null);
  const [pendingBobsRevisionManifestId, setPendingBobsRevisionManifestId] = useState<string | null>(null);
  const [pendingNormalRevisionManifestId, setPendingNormalRevisionManifestId] = useState<string | null>(null);
  const [lastNormalSentQueueSignature, setLastNormalSentQueueSignature] = useState<string | null>(null);
  const [isLoadingBobsJobs, setIsLoadingBobsJobs] = useState(false);
  const [loadingBobsJobDetails, setLoadingBobsJobDetails] = useState<string[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const [todayDateLabel, setTodayDateLabel] = useState(formatTodayDateLabel);
  const hydratedBobsManifestIdRef = useRef<string | null>(null);
  const hydratedBobsSelectionManifestIdRef = useRef<string | null>(null);
  const activeHistoryManifestIdRef = useRef<string | null>(null);
  const sentHistoryRef = useRef<ShipmentManifest[]>([]);
  const handleDroppedPathRef = useRef<(path: string, excelPaths: string[]) => Promise<void>>(async () => undefined);

  function setActiveHistoryManifestId(nextManifestId: string | null) {
    activeHistoryManifestIdRef.current = nextManifestId;
    setActiveHistoryManifestIdState(nextManifestId);
  }

  useEffect(() => {
    sentHistoryRef.current = sentHistory;
  }, [sentHistory]);

  useEffect(() => {
    handleDroppedPathRef.current = handleDroppedPath;
  });

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    listenForFolderDrops(async (paths) => {
      const excelPaths = paths.filter(isLikelyExcelPath);
      const hasDroppedPdf = paths.some(isLikelyPdfPath);
      for (const path of paths) {
        if (hasDroppedPdf && isLikelyExcelPath(path)) {
          continue;
        }
        await handleDroppedPathRef.current(path, excelPaths);
      }
    }).then((unlisten) => {
      cleanup = unlisten;
    });
    return () => cleanup?.();
  }, []);

  useEffect(() => {
    let timeoutId: ReturnType<typeof window.setTimeout>;
    const updateTodayDateLabel = () => {
      setTodayDateLabel(formatTodayDateLabel());
      timeoutId = window.setTimeout(updateTodayDateLabel, getMillisecondsUntilTomorrow());
    };

    timeoutId = window.setTimeout(updateTodayDateLabel, getMillisecondsUntilTomorrow());
    return () => window.clearTimeout(timeoutId);
  }, []);

  useEffect(() => {
    let isCurrent = true;
    getSenderBackendUrl()
      .then((backendUrl) => {
        if (isCurrent) {
          setSenderBackendUrl(backendUrl);
        }
      })
      .catch((error: unknown) => {
        console.warn('전송 백엔드 URL을 확인하지 못했습니다.', error);
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  const dayOptions = useMemo(
    () => Array.from({ length: getDaysInMonth(selectedYear, selectedMonth) }, (_, index) => index + 1),
    [selectedMonth, selectedYear],
  );

  const activeHistoryManifest = useMemo(
    () => (activeHistoryManifestId ? sentHistory.find((manifest) => manifest.id === activeHistoryManifestId) ?? null : null),
    [activeHistoryManifestId, sentHistory],
  );
  const activeManifest = useMemo(() => {
    if (activeHistoryManifestId !== null) {
      return activeHistoryManifest;
    }

    return manifests.find((manifest) => manifest.id === activeManifestId)
      ?? (activeReviewManifest?.id === activeManifestId ? activeReviewManifest : null)
      ?? manifests[manifests.length - 1]
      ?? null;
  }, [activeHistoryManifest, activeHistoryManifestId, activeManifestId, activeReviewManifest, manifests]);
  const activeManifestDisplayTitle = activeManifest ? getManifestDisplayTitle(activeManifest) : '';
  const activeManifestIsQueued = activeManifest !== null
    && activeHistoryManifestId === null
    && (manifests.some((manifest) => manifest.id === activeManifest.id) || activeReviewManifest?.id === activeManifest.id);
  const activeManifestYearContext = activeManifestIsQueued
    ? selectedYear
    : activeManifest
      ? getYearFromTimestamp(activeManifest.created_at) ?? selectedYear
      : selectedYear;
  const activeManifestDateFolderLabel = activeManifest ? getManifestDateFolderLabel(activeManifest, activeManifestYearContext) : '';
  const activeBobsHistorySelection = useMemo(
    () => (activeHistoryManifest ? getBobsHistorySelection(activeHistoryManifest) : null),
    [activeHistoryManifest],
  );
  const isBobsHistoryRevisionContext = activeBobsHistorySelection !== null
    && activeHistoryManifest?.id === activeBobsHistorySelection.manifestId;
  const pendingBobsRevisionManifest = pendingBobsRevisionManifestId
    ? manifests.find((manifest) => manifest.id === pendingBobsRevisionManifestId) ?? null
    : null;
  const pendingNormalRevisionManifest = pendingNormalRevisionManifestId
    ? manifests.find((manifest) => manifest.id === pendingNormalRevisionManifestId) ?? null
    : null;
  const isBobsRevisionPending = pendingBobsRevisionManifestId !== null;
  const isNormalRevisionPending = pendingNormalRevisionManifestId !== null;
  const sentHistoryRows = useMemo(
    () => sentHistory.map((manifest, index) => {
      const dateParts = getSentHistoryDateParts(manifest);
      return {
        manifest,
        index,
        dateParts,
      };
    }),
    [sentHistory],
  );
  const selectedHistoryYear = getSelectedHistoryFilter(historyYearFilter);
  const selectedHistoryMonth = getSelectedHistoryFilter(historyMonthFilter);
  const selectedHistoryDay = getSelectedHistoryFilter(historyDayFilter);
  const normalizedHistorySearchQuery = useMemo(() => normalizeHistorySearchQuery(historySearchQuery), [historySearchQuery]);
  const currentLocalDateKey = useMemo(() => getLocalDateKey(new Date()), [todayDateLabel]);
  const historyYearOptions = useMemo(
    () => getHistoryDateOptions(sentHistoryRows, (row) => row.dateParts?.year ?? null),
    [sentHistoryRows],
  );
  const historyMonthOptions = useMemo(
    () => getHistoryDateOptions(
      sentHistoryRows.filter((row) => selectedHistoryYear === null || row.dateParts?.year === selectedHistoryYear),
      (row) => row.dateParts?.month ?? null,
    ),
    [selectedHistoryYear, sentHistoryRows],
  );
  const historyDayOptions = useMemo(
    () => getHistoryDateOptions(
      sentHistoryRows.filter((row) => (
        (selectedHistoryYear === null || row.dateParts?.year === selectedHistoryYear)
        && (selectedHistoryMonth === null || row.dateParts?.month === selectedHistoryMonth)
      )),
      (row) => row.dateParts?.day ?? null,
    ),
    [selectedHistoryMonth, selectedHistoryYear, sentHistoryRows],
  );
  const filteredHistoryRows = useMemo(
    () => sentHistoryRows.filter((row) => (
      (selectedHistoryYear === null || row.dateParts?.year === selectedHistoryYear)
      && (selectedHistoryMonth === null || row.dateParts?.month === selectedHistoryMonth)
      && (selectedHistoryDay === null || row.dateParts?.day === selectedHistoryDay)
      && historyRowMatchesSearch(row, normalizedHistorySearchQuery)
    )).slice().sort((left, right) => compareHistoryRowsByShipmentDate(left, right, shipmentDateSortOrder)),
    [normalizedHistorySearchQuery, selectedHistoryDay, selectedHistoryMonth, selectedHistoryYear, sentHistoryRows, shipmentDateSortOrder],
  );
  const activeManifestMatchesHistorySearch = activeHistoryManifest !== null
    && normalizedHistorySearchQuery.raw !== ''
    && filteredHistoryRows.some((row) => row.manifest.id === activeHistoryManifest.id);
  const activeHistorySearchQuery = activeManifestMatchesHistorySearch ? historySearchQuery.trim() : '';
  const isLoadingBobsJobDetail = selectedBobsJob ? loadingBobsJobDetails.includes(selectedBobsJob) : false;
  const selectedBobsJobDetail = selectedBobsJob ? bobsJobDetailCache[selectedBobsJob] ?? null : null;
  const selectedBobsJobDetailError = selectedBobsJob ? bobsJobDetailErrors[selectedBobsJob] ?? '' : '';
  const selectedBobsJobMeta = isLoadingBobsJobDetail
    ? 'detail 불러오는 중'
    : selectedBobsJobDetail
      ? `${Object.keys(selectedBobsJobDetail.sequences).length} SEQ · ${selectedBobsJobDetail.scenes.length} scenes`
      : selectedBobsJobDetailError
        ? `detail 오류: ${selectedBobsJobDetailError}`
        : selectedBobsJob
          ? 'job 선택됨'
          : 'job을 선택하세요';
  const selectedBobsSceneEntries = useMemo<BobsSelectedScene[]>(() => {
    if (!selectedBobsJobDetail) {
      return [];
    }

    const jobDetail = selectedBobsJobDetail;
    if (bobsSelectionMode === 'SEQ') {
      const selectedSequences = getSelectedJobValues(selectedBobsSequencesByJob, jobDetail.job);
      const scenes = selectedSequences.flatMap((sequence) => jobDetail.sequences[sequence] ?? []);
      return Array.from(new Set(scenes)).map((scene) => ({ jobDetail, scene }));
    }

    return getSelectedJobValues(selectedBobsScenesByJob, jobDetail.job)
      .filter((scene) => jobDetail.scenes.includes(scene))
      .map((scene) => ({ jobDetail, scene }));
  }, [bobsSelectionMode, selectedBobsJobDetail, selectedBobsScenesByJob, selectedBobsSequencesByJob]);
  const canSendPendingBobsRevision = isBobsRevisionPending && pendingBobsRevisionManifest !== null && manifests.length === 1;
  const canSendPendingNormalRevision = isNormalRevisionPending && pendingNormalRevisionManifest !== null && manifests.length === 1;
  const canCreateDirectBobsRevision = isBobsHistoryRevisionContext && selectedBobsSceneEntries.length > 0;
  const hasRevisionContext = isBobsHistoryRevisionContext || isBobsRevisionPending || isNormalRevisionPending;
  const visibleTransferManifests = useMemo(
    () => manifests.filter((manifest) => !isBobsManifest(manifest)),
    [manifests],
  );
  const queuedManifestsForNormalSend = senderMode === 'transfer' ? visibleTransferManifests : manifests;
  const normalSendQueueSignature = useMemo(() => getNormalSendQueueSignature(queuedManifestsForNormalSend), [queuedManifestsForNormalSend]);
  const isNormalSendUnchangedSinceLastSend = queuedManifestsForNormalSend.length > 0 && normalSendQueueSignature === lastNormalSentQueueSignature;
  const isNormalSendDisabled = queuedManifestsForNormalSend.length === 0 || isBusy || isNormalSendUnchangedSinceLastSend || isBobsRevisionPending || isNormalRevisionPending || isBobsHistoryRevisionContext;
  const isRevisionSendDisabled = isBusy || !hasRevisionContext || (isBobsHistoryRevisionContext && !canCreateDirectBobsRevision);
  const bobsWarningsMessage = getBobsWarningsMessage([
    ...bobsJobWarnings,
    ...(selectedBobsJobDetail?.warnings ?? []),
  ]);
  const isRoutineBobsStatus = (
    status === '밥스버거 job 목록을 불러오고 있습니다.'
    || /^밥스버거 job \d+개를 불러왔습니다\.$/.test(status)
    || /^[^\s]+ 상세 정보를 불러왔습니다\.$/.test(status)
  );
  const shouldShowStatus = status !== '' && !isRoutineBobsStatus;
  const autoBobsGeneratedQueue = useMemo(() => {
    const emptyQueue = { manifests: [], reviewManifest: null } satisfies { manifests: ShipmentManifest[]; reviewManifest: ShipmentManifest | null };
    if (senderMode !== 'bobs' || activeHistoryManifestId !== null || selectedBobsSceneEntries.length === 0) {
      return emptyQueue;
    }

    const selectedDate = { year: selectedYear, month: selectedMonth, day: selectedDay };
    if (activeBobsRetakePdfSelection && selectedBobsJobDetail && activeBobsRetakePdfSelection.job === selectedBobsJobDetail.job) {
      const bobsManifests = createBobsRetakePdfManifests(activeBobsRetakePdfSelection, selectedBobsJobDetail, selectedDate);
      return {
        manifests: bobsManifests,
        reviewManifest: createBobsRetakeReviewManifest(bobsManifests),
      };
    }

    const bobsManifest = createBobsBatchManifest(
      selectedBobsSceneEntries,
      bobsTkNumber,
      selectedDate,
      false,
      bobsSelectionMode === 'SEQ' ? 'batch' : 'TK',
    );
    return {
      manifests: bobsManifest ? [bobsManifest] : [],
      reviewManifest: null,
    };
  }, [activeBobsRetakePdfSelection, activeHistoryManifestId, bobsSelectionMode, bobsTkNumber, selectedBobsJobDetail, selectedBobsSceneEntries, selectedDay, selectedMonth, selectedYear, senderMode]);

  useEffect(() => {
    setLastBobsSequenceRangeAnchor(null);
    setLastBobsSceneRangeAnchor(null);
  }, [selectedBobsJob]);

  const historyEmptyText = historyLoadError
    ? `이전 기록 오류: ${historyLoadError}`
    : sentHistory.length === 0
      ? '아직 이전 전송 기록이 없습니다.'
      : normalizedHistorySearchQuery.raw !== ''
        ? '검색어와 날짜 필터에 맞는 이전 전송 기록이 없습니다.'
        : '선택한 날짜에 맞는 이전 전송 기록이 없습니다.';
  const shouldShowHistoryDiagnostic = historyLoadError !== '' || sentHistory.length === 0;
  const historyDiagnosticText = shouldShowHistoryDiagnostic ? getSenderDbDiagnostic(senderHealth, senderHealthError) : '';

  useEffect(() => {
    const jobToFetch = selectedBobsJob;
    if (!jobToFetch || bobsJobDetailCache[jobToFetch] || bobsJobDetailErrors[jobToFetch] || loadingBobsJobDetails.includes(jobToFetch)) {
      return;
    }

    setLoadingBobsJobDetails((currentJobs) => Array.from(new Set([...currentJobs, jobToFetch])));
    setBobsJobDetailErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[jobToFetch];
      return nextErrors;
    });

    fetchBobsCatalogJob(jobToFetch)
      .then((jobDetail) => {
        setBobsJobDetailCache((currentCache) => ({ ...currentCache, [jobToFetch]: jobDetail }));
        setSelectedBobsSequencesByJob((currentSelections) => {
          const availableSequences = new Set(Object.keys(jobDetail.sequences));
          return {
            ...currentSelections,
            [jobToFetch]: getSelectedJobValues(currentSelections, jobToFetch).filter((sequence) => availableSequences.has(sequence)),
          };
        });
        setSelectedBobsScenesByJob((currentSelections) => {
          const availableScenes = new Set(jobDetail.scenes);
          return {
            ...currentSelections,
            [jobToFetch]: getSelectedJobValues(currentSelections, jobToFetch).filter((scene) => availableScenes.has(scene)),
          };
        });
        setStatus(`${jobDetail.job} 상세 정보를 불러왔습니다.`);
      })
      .catch((error: unknown) => {
        const message = getErrorMessage(error, '밥스버거 job 상세 정보를 불러오지 못했습니다.');
        setBobsJobDetailErrors((currentErrors) => ({ ...currentErrors, [jobToFetch]: message }));
        setStatus(message);
      })
      .finally(() => {
        setLoadingBobsJobDetails((currentJobs) => currentJobs.filter((currentJob) => currentJob !== jobToFetch));
      });
  }, [bobsJobDetailCache, bobsJobDetailErrors, loadingBobsJobDetails, selectedBobsJob]);

  useEffect(() => {
    if (!activeBobsHistorySelection) {
      hydratedBobsManifestIdRef.current = null;
      hydratedBobsSelectionManifestIdRef.current = null;
      return;
    }

    if (hydratedBobsManifestIdRef.current === activeBobsHistorySelection.manifestId) {
      return;
    }

    hydratedBobsManifestIdRef.current = activeBobsHistorySelection.manifestId;
    hydratedBobsSelectionManifestIdRef.current = null;
    setSenderMode('bobs');
    if (bobsJobs.length === 0 && !isLoadingBobsJobs) {
      void loadBobsJobs();
    }
    setBobsJobDetailErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[activeBobsHistorySelection.job];
      return nextErrors;
    });
    setSelectedBobsJob(activeBobsHistorySelection.job);
    setBobsTkNumber(activeBobsHistorySelection.tkNumber);
  }, [activeBobsHistorySelection, bobsJobs.length, isLoadingBobsJobs]);

  useEffect(() => {
    if (!activeBobsHistorySelection || !selectedBobsJobDetail || selectedBobsJobDetail.job !== activeBobsHistorySelection.job) {
      return;
    }

    if (hydratedBobsSelectionManifestIdRef.current === activeBobsHistorySelection.manifestId) {
      return;
    }

    hydratedBobsSelectionManifestIdRef.current = activeBobsHistorySelection.manifestId;
    const availableScenes = new Set(selectedBobsJobDetail.scenes);
    const selectedScenes = getUniqueValues(activeBobsHistorySelection.scenes.map(getBobsCatalogSceneFromDisplayScene)).filter((scene) => availableScenes.has(scene));
    const selectedSequences = getRepresentingBobsSequences(selectedBobsJobDetail, selectedScenes);

    if (selectedSequences.length > 0) {
      setBobsSelectionMode('SEQ');
      setSelectedBobsSequencesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, activeBobsHistorySelection.job, selectedSequences));
      setSelectedBobsScenesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, activeBobsHistorySelection.job, []));
      return;
    }

    setBobsSelectionMode('scene');
    setSelectedBobsSequencesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, activeBobsHistorySelection.job, []));
    setSelectedBobsScenesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, activeBobsHistorySelection.job, selectedScenes));
  }, [activeBobsHistorySelection, selectedBobsJobDetail]);

  useEffect(() => {
    if (!pendingBobsRetakePdf || !selectedBobsJobDetail || selectedBobsJobDetail.job !== pendingBobsRetakePdf.job) {
      return;
    }

    const matchedRows = getMatchedBobsRetakeRows(selectedBobsJobDetail, pendingBobsRetakePdf.rows);
    const matchedScenes = getUniqueValues(matchedRows.map((row) => row.scene));
    setBobsSelectionMode('scene');
    setSelectedBobsSequencesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, pendingBobsRetakePdf.job, []));
    setSelectedBobsScenesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, pendingBobsRetakePdf.job, matchedScenes));
    if (matchedRows.length === 0) {
      setActiveBobsRetakePdfSelection(null);
      setStatus(`${pendingBobsRetakePdf.job} retake PDF를 읽었지만 catalog와 일치하는 scene이 없습니다.`);
      return;
    }
    setActiveBobsRetakePdfSelection({
      sourcePath: pendingBobsRetakePdf.sourcePath,
      job: pendingBobsRetakePdf.job,
      rows: matchedRows,
    });
    const tkValues = getUniqueValues(matchedRows.map((row) => row.tk));
    setStatus(`${pendingBobsRetakePdf.job} retake PDF에서 ${matchedScenes.length}개 scene, TK ${tkValues.join(', ')}을 선택했습니다.`);
  }, [pendingBobsRetakePdf, selectedBobsJobDetail]);

  useEffect(() => {
    if (senderMode !== 'bobs' || activeHistoryManifestId !== null) {
      return;
    }

    const nextBobsManifests = autoBobsGeneratedQueue.manifests;
    if (nextBobsManifests.length === 0) {
      setManifests((currentManifests) => {
        const nextManifests = currentManifests.filter((manifest) => !isBobsManifest(manifest));
        return areManifestQueuesEqual(currentManifests, nextManifests) ? currentManifests : nextManifests;
      });
      setActiveReviewManifest(null);
      setPendingBobsRevisionManifestId(null);
      setActiveManifestId(null);
      return;
    }

    setManifests((currentManifests) => {
      const nextManifests = [
        ...currentManifests.filter((manifest) => !isBobsManifest(manifest)),
        ...nextBobsManifests,
      ];
      return areManifestQueuesEqual(currentManifests, nextManifests) ? currentManifests : nextManifests;
    });
    setActiveHistoryManifestId(null);
    setActiveReviewManifest(autoBobsGeneratedQueue.reviewManifest);
    setPendingBobsRevisionManifestId(null);
    setPendingNormalRevisionManifestId(null);
    setActiveManifestId(autoBobsGeneratedQueue.reviewManifest?.id ?? nextBobsManifests[nextBobsManifests.length - 1]?.id ?? null);
  }, [activeHistoryManifestId, autoBobsGeneratedQueue, senderMode]);

  useEffect(() => {
    const lastDay = getDaysInMonth(selectedYear, selectedMonth);
    if (selectedDay > lastDay) {
      setSelectedDay(lastDay);
    }
  }, [selectedDay, selectedMonth, selectedYear]);

  useEffect(() => {
    let isCurrent = true;
    let intervalId: ReturnType<typeof window.setInterval>;
    clearLegacySentHistory();
    void refreshSentHistory(true, false, () => isCurrent);
    intervalId = window.setInterval(() => {
      void refreshSentHistory(false, false, () => isCurrent);
    }, 10000);

    return () => {
      isCurrent = false;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (normalizedHistorySearchQuery.raw === '' || filteredHistoryRows.length === 0) {
      return;
    }

    const currentActiveHistoryId = activeHistoryManifest?.id ?? activeHistoryManifestId;
    if (currentActiveHistoryId && filteredHistoryRows.some((row) => row.manifest.id === currentActiveHistoryId)) {
      return;
    }
    if (activeHistoryManifestId === null && activeManifestId && manifests.some((manifest) => manifest.id === activeManifestId)) {
      return;
    }

    handleSelectSentHistoryManifest(filteredHistoryRows[0].manifest);
  }, [activeHistoryManifest?.id, activeHistoryManifestId, activeManifestId, filteredHistoryRows, manifests, normalizedHistorySearchQuery]);

  async function refreshSentHistory(clearOnFailure = false, showStatus = false, isCurrent = () => true) {
    const { historyResult, healthResult } = await fetchSentHistoryAndHealth();
    if (!isCurrent()) {
      return;
    }

    applyHistoryResult(historyResult, clearOnFailure);
    applyHealthResult(healthResult);
    if (showStatus && historyResult.status === 'fulfilled' && healthResult.status === 'fulfilled') {
      setStatus('이전 전송 기록을 새로고침했습니다.');
    }
  }

  function applyHistoryResult(result: PromiseSettledResult<ShipmentManifest[]>, clearOnFailure: boolean) {
    if (result.status === 'fulfilled') {
      setSentHistory(result.value);
      setHistoryLoadError('');
      return;
    }

    console.warn('이전 전송 기록을 불러오지 못했습니다.', result.reason);
    if (clearOnFailure) {
      setSentHistory([]);
    }
    setHistoryLoadError(getErrorMessage(result.reason, '이전 전송 기록을 불러오지 못했습니다.'));
  }

  function applyHealthResult(result: PromiseSettledResult<SenderHealth>) {
    if (result.status === 'fulfilled') {
      setSenderHealth(result.value);
      setSenderHealthError('');
      return;
    }

    console.warn('전송 기록 DB 상태를 확인하지 못했습니다.', result.reason);
    setSenderHealthError(getErrorMessage(result.reason, 'DB 상태를 확인하지 못했습니다.'));
  }

  async function loadBobsJobs() {
    setIsLoadingBobsJobs(true);
    setBobsJobsError('');
    setStatus('밥스버거 job 목록을 불러오고 있습니다.');
    try {
      const catalog = await fetchBobsCatalogJobs();
      const currentJobs = getCurrentBobsJobs(catalog.jobs);
      setBobsJobs(currentJobs);
      setBobsJobWarnings(catalog.warnings);
      setBobsJobDetailErrors({});
      setSelectedBobsJob((currentJob) => (currentJob && currentJobs.includes(currentJob) ? currentJob : null));
      setStatus(`밥스버거 job ${currentJobs.length}개를 불러왔습니다.`);
    } catch (error) {
      const message = getErrorMessage(error, '밥스버거 job 목록을 불러오지 못했습니다.');
      setBobsJobsError(message);
      setStatus(message);
    } finally {
      setIsLoadingBobsJobs(false);
    }
  }

  function clearBobsRetakePdfSelection() {
    setPendingBobsRetakePdf(null);
    setActiveBobsRetakePdfSelection(null);
  }

  function clearPendingBobsRevisionDraft() {
    const queuedRevisionManifestId = pendingBobsRevisionManifestId;
    setPendingBobsRevisionManifestId(null);
    if (queuedRevisionManifestId) {
      setManifests((currentManifests) => (
        currentManifests.length === 1 && currentManifests[0].id === queuedRevisionManifestId ? [] : currentManifests
      ));
    }
  }

  function clearPendingNormalRevisionDraft() {
    const queuedRevisionManifestId = pendingNormalRevisionManifestId;
    setPendingNormalRevisionManifestId(null);
    if (queuedRevisionManifestId) {
      setManifests((currentManifests) => (
        currentManifests.length === 1 && currentManifests[0].id === queuedRevisionManifestId ? [] : currentManifests
      ));
    }
  }

  function clearPendingRevisionDrafts() {
    clearPendingBobsRevisionDraft();
    clearPendingNormalRevisionDraft();
  }

  function handleSelectQueuedManifest(manifest: ShipmentManifest) {
    if (manifest.id !== pendingBobsRevisionManifestId) {
      clearPendingBobsRevisionDraft();
    }
    if (manifest.id !== pendingNormalRevisionManifestId) {
      clearPendingNormalRevisionDraft();
    }
    setActiveHistoryManifestId(null);
    setActiveManifestId(manifest.id);
  }

  function handleSelectSentHistoryManifest(manifest: ShipmentManifest) {
    clearBobsRetakePdfSelection();
    clearPendingRevisionDrafts();
    setActiveReviewManifest(null);
    if (!isBobsManifest(manifest)) {
      setSenderMode('transfer');
      setManifests((currentManifests) => currentManifests.filter((currentManifest) => !isBobsManifest(currentManifest)));
    }
    activeHistoryManifestIdRef.current = manifest.id;
    setActiveHistoryManifestId(manifest.id);
    setActiveManifestId(manifest.id);
  }

  function handleSetSenderMode(nextMode: SenderMode) {
    if (nextMode !== 'bobs') {
      clearBobsRetakePdfSelection();
      setManifests((currentManifests) => currentManifests.filter((manifest) => !isBobsManifest(manifest)));
      setActiveReviewManifest(null);
      setActiveManifestId(null);
    }
    setSenderMode(nextMode);
    if (nextMode === 'bobs' && bobsJobs.length === 0 && !isLoadingBobsJobs) {
      void loadBobsJobs();
    }
  }

  function handleToggleBobsJob(job: string) {
    clearBobsRetakePdfSelection();
    if (job === '') {
      setSelectedBobsJob(null);
      setSelectedBobsSequencesByJob({});
      setSelectedBobsScenesByJob({});
      setBobsTkNumber('');
      setLastBobsSequenceRangeAnchor(null);
      setLastBobsSceneRangeAnchor(null);
      return;
    }
    if (selectedBobsJob === job) {
      return;
    }
    setBobsJobDetailErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[job];
      return nextErrors;
    });
    setSelectedBobsJob(job);
    setSelectedBobsSequencesByJob({});
    setSelectedBobsScenesByJob({});
    setBobsTkNumber('');
    setLastBobsSequenceRangeAnchor(null);
    setLastBobsSceneRangeAnchor(null);
  }

  function handleResetBobsSelection(): void {
    clearBobsRetakePdfSelection();
    setSelectedBobsJob(null);
    setSelectedBobsSequencesByJob({});
    setSelectedBobsScenesByJob({});
    setLastBobsSequenceRangeAnchor(null);
    setLastBobsSceneRangeAnchor(null);
    setBobsTkNumber('');
    setBobsSelectionMode('SEQ');
    clearPendingRevisionDrafts();
    setActiveHistoryManifestId(null);
    setActiveManifestId(null);
    hydratedBobsManifestIdRef.current = null;
    hydratedBobsSelectionManifestIdRef.current = null;
  }

  function handleToggleBobsSequence(job: string, sequence: string, visibleSequences: string[], isRangeSelection: boolean) {
    const rangeAnchor = lastBobsSequenceRangeAnchor;
    clearBobsRetakePdfSelection();
    setSelectedBobsSequencesByJob((currentSelections) => ({
      ...currentSelections,
      [job]: isRangeSelection && rangeAnchor?.job === job
        ? addRangeSelection(getSelectedJobValues(currentSelections, job), visibleSequences, rangeAnchor.value, sequence)
        : toggleSelection(getSelectedJobValues(currentSelections, job), sequence),
    }));
    setLastBobsSequenceRangeAnchor({ job, value: sequence });
  }

  function handleToggleBobsScene(job: string, scene: string, visibleScenes: string[], isRangeSelection: boolean) {
    const rangeAnchor = lastBobsSceneRangeAnchor;
    clearBobsRetakePdfSelection();
    setSelectedBobsScenesByJob((currentSelections) => ({
      ...currentSelections,
      [job]: isRangeSelection && rangeAnchor?.job === job
        ? addRangeSelection(getSelectedJobValues(currentSelections, job), visibleScenes, rangeAnchor.value, scene)
        : toggleSelection(getSelectedJobValues(currentSelections, job), scene),
    }));
    setLastBobsSceneRangeAnchor({ job, value: scene });
  }

  async function handleDroppedPath(path: string, excelPaths: string[] = []) {
    if (isLikelyPdfPath(path)) {
      setIsBusy(true);
      setStatus('Bobs retake PDF인지 확인하고 있습니다.');
      try {
        const parseOptions = excelPaths.length > 0 ? { excel_paths: excelPaths } : undefined;
        const parseResult = await parseBobsRetakePdf(path, parseOptions);
        if (parseResult.matched) {
          handleApplyBobsRetakePdf(path, parseResult);
          return;
        }
        if (parseResult.recognized === true || isLikelyBobsRetakePdfPath(path)) {
          setStatus(parseResult.error || 'Bobs retake PDF로 보이지만 필요한 값을 찾지 못했습니다.');
          return;
        }
      } catch (error) {
        if (isLikelyBobsRetakePdfPath(path)) {
          setStatus(`Bobs retake PDF를 확인하지 못했습니다: ${getErrorMessage(error, '알 수 없는 오류')}`);
          return;
        }
        console.warn('Bobs retake PDF 파싱을 건너뛰고 일반 스캔을 시도합니다.', error);
      } finally {
        setIsBusy(false);
      }
    }
    await handleScan(path);
  }

  function handleApplyBobsRetakePdf(path: string, parseResult: BobsRetakePdfParseResult) {
    if (!parseResult.due_date || parseResult.job.trim() === '' || parseResult.rows.length === 0) {
      setStatus(parseResult.error || 'Bobs retake PDF에서 필요한 값을 찾지 못했습니다.');
      return;
    }

    const tkValues = getUniqueValues(parseResult.rows.map((row) => row.tk));
    setSelectedYear(parseResult.due_date.year);
    setSelectedMonth(parseResult.due_date.month);
    setSelectedDay(parseResult.due_date.day);
    setSenderMode('bobs');
    if (bobsJobs.length === 0 && !isLoadingBobsJobs) {
      void loadBobsJobs();
    }
    setPendingBobsRevisionManifestId(null);
    setPendingNormalRevisionManifestId(null);
    setActiveHistoryManifestId(null);
    setActiveManifestId(null);
    setBobsSelectionMode('scene');
    setBobsTkNumber(tkValues.length === 1 ? tkValues[0] : '');
    setBobsJobDetailErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[parseResult.job];
      return nextErrors;
    });
    setSelectedBobsJob(parseResult.job);
    setSelectedBobsSequencesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, parseResult.job, []));
    setSelectedBobsScenesByJob((currentSelections) => replaceSelectedJobValues(currentSelections, parseResult.job, []));
    setPendingBobsRetakePdf({ sourcePath: path, job: parseResult.job, rows: parseResult.rows });
    setActiveBobsRetakePdfSelection(null);
    setStatus(`${parseResult.job} retake PDF를 읽었습니다. catalog detail을 불러와 scene을 선택합니다.`);
  }

  async function handleScan(path: string) {
    const selectedHistoryManifestId = activeHistoryManifestIdRef.current;
    const selectedHistoryManifest = selectedHistoryManifestId
      ? sentHistoryRef.current.find((manifest) => manifest.id === selectedHistoryManifestId) ?? null
      : null;
    const selectedNormalRevisionSourceManifest = selectedHistoryManifest && !isBobsManifest(selectedHistoryManifest) ? selectedHistoryManifest : null;
    setIsBusy(true);
    setStatus('폴더 내용을 읽고 있습니다.');
    try {
      const nextManifest = await scanFolder(path);
      clearBobsRetakePdfSelection();
      setPendingBobsRevisionManifestId(null);
      const detectedNormalRevisionSourceManifest = findChangedNormalRevisionSourceManifest(nextManifest, sentHistoryRef.current, selectedYear);
      const normalRevisionSourceManifest = selectedNormalRevisionSourceManifest ?? detectedNormalRevisionSourceManifest;
      if (normalRevisionSourceManifest) {
        const revisionManifest = createRevisionReplacementManifest(nextManifest, normalRevisionSourceManifest);
        setPendingNormalRevisionManifestId(revisionManifest.id);
        setManifests([revisionManifest]);
        setActiveHistoryManifestId(null);
        setActiveReviewManifest(null);
        setActiveManifestId(revisionManifest.id);
        const folderDate = getDateFromPath(revisionManifest.source_path, selectedYear) ?? getDateFromPath(path, selectedYear);
        if (folderDate) {
          setSelectedYear(folderDate.year);
          setSelectedMonth(folderDate.month);
          setSelectedDay(folderDate.day);
        }
        setSenderMode('transfer');
        setStatus(`${getManifestDisplayTitle(normalRevisionSourceManifest)}와 같은 선적 날짜/제목의 변경된 목록을 수정전송용으로 불러왔습니다.`);
        return;
      }
      setPendingNormalRevisionManifestId(null);
      setManifests((currentManifests) => [
        ...(isBobsRevisionPending || isNormalRevisionPending ? [] : currentManifests.filter((currentManifest) => currentManifest.source_path !== nextManifest.source_path)),
        nextManifest,
      ]);
      setActiveHistoryManifestId(null);
      setActiveReviewManifest(null);
      setActiveManifestId(nextManifest.id);
      const folderDate = getDateFromPath(nextManifest.source_path, selectedYear) ?? getDateFromPath(path, selectedYear);
      if (folderDate) {
        setSelectedYear(folderDate.year);
        setSelectedMonth(folderDate.month);
        setSelectedDay(folderDate.day);
      }
      setSenderMode('transfer');
      setStatus(`${getManifestDisplayTitle(nextManifest)} 목록을 불러왔습니다.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '폴더를 읽지 못했습니다.');
    } finally {
      setIsBusy(false);
    }
  }

  function handleClearQueue() {
    setManifests([]);
    setActiveReviewManifest(null);
    setPendingBobsRevisionManifestId(null);
    setPendingNormalRevisionManifestId(null);
    setActiveHistoryManifestId(null);
    setActiveManifestId(null);
    setNote('');
  }

  async function handleSend() {
    if (isBobsRevisionPending || isNormalRevisionPending || isBobsHistoryRevisionContext) {
      setStatus('이전 기록 수정 목록은 수정전송으로만 보낼 수 있습니다.');
      return;
    }
    if (queuedManifestsForNormalSend.length === 0) {
      setStatus('먼저 폴더를 드래그앤드롭하세요.');
      return;
    }
    if (isNormalSendUnchangedSinceLastSend) {
      setStatus('목록이 바뀌지 않아 다시 전송하지 않습니다.');
      return;
    }
    await sendQueuedManifests(queuedManifestsForNormalSend, 'normal');
  }

  async function handleSendRevision() {
    if (isBobsHistoryRevisionContext) {
      if (!activeHistoryManifest) {
        setStatus('수정전송할 이전 밥스버거 기록을 다시 선택하세요.');
        return;
      }
      const selectedDate = { year: selectedYear, month: selectedMonth, day: selectedDay };
      const generatedManifest = createBobsBatchManifest(
        selectedBobsSceneEntries,
        bobsTkNumber,
        selectedDate,
        false,
        bobsSelectionMode === 'SEQ' ? 'batch' : 'TK',
      );
      if (!generatedManifest) {
        setStatus('밥스버거 job과 SEQ 또는 scene을 선택한 뒤 수정전송하세요.');
        return;
      }
      const revisionManifest = createBobsRevisionManifest(generatedManifest, activeHistoryManifest);
      await sendQueuedManifests([revisionManifest], 'revision');
      return;
    }
    if (isNormalRevisionPending) {
      if (!canSendPendingNormalRevision || !pendingNormalRevisionManifest) {
        handleClearQueue();
        setStatus('수정전송 대기 목록이 유효하지 않아 전송하지 않고 비웠습니다.');
        return;
      }
      await sendQueuedManifests([pendingNormalRevisionManifest], 'revision');
      return;
    }
    if (!isBobsRevisionPending) {
      handleClearQueue();
      setStatus('수정전송 대기 중인 이전 기록이 없어 전송 목록을 비웠습니다.');
      return;
    }
    if (!canSendPendingBobsRevision || !pendingBobsRevisionManifest) {
      handleClearQueue();
      setStatus('수정전송 대기 목록이 유효하지 않아 전송하지 않고 비웠습니다.');
      return;
    }
    await sendQueuedManifests([pendingBobsRevisionManifest], 'revision');
  }

  async function sendQueuedManifests(queuedManifests: ShipmentManifest[], sendMode: 'normal' | 'revision') {
    if (queuedManifests.length === 0) {
      setStatus(sendMode === 'revision' ? '수정전송할 목록이 없습니다.' : '먼저 폴더를 드래그앤드롭하세요.');
      return;
    }
    setIsBusy(true);
    const manifestsToSend = queuedManifests.map((queuedManifest) => ({
      ...queuedManifest,
      note,
    }));
    try {
      const auditAction = sendMode === 'revision' ? 'revision' : 'send';
      for (const manifestToSend of manifestsToSend) {
        await sendManifest(manifestToSend, auditAction);
      }
      setNote('');
      setSentHistory((currentHistory) => mergeSentHistory(manifestsToSend, currentHistory));
      const refreshResult = await fetchSentHistoryAndHealth();
      applyHistoryResult(refreshResult.historyResult, false);
      applyHealthResult(refreshResult.healthResult);
      const firstSentManifest = manifestsToSend[0];
      if (!firstSentManifest) {
        setStatus(sendMode === 'revision' ? '수정전송할 목록이 없습니다.' : '먼저 폴더를 드래그앤드롭하세요.');
        return;
      }
      if (sendMode === 'revision') {
        setManifests([]);
        setPendingBobsRevisionManifestId(null);
        setPendingNormalRevisionManifestId(null);
        setActiveHistoryManifestId(firstSentManifest.id);
        setActiveManifestId(firstSentManifest.id);
      } else {
        setLastNormalSentQueueSignature(getNormalSendQueueSignature(manifestsToSend));
      }
      const message = sendMode === 'revision'
        ? `${getManifestDisplayTitle(firstSentManifest)} 수정전송이 완료되었습니다.`
        : queuedManifests.length === 1
          ? `${getManifestDisplayTitle(firstSentManifest)} 전송이 완료되었습니다.`
          : `${queuedManifests.length}개 폴더 전송이 완료되었습니다.`;
      setStatus(message);
      await notify('선적전송', message);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '전송하지 못했습니다.');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <main className="shell">
      <div className="sender-layout">
        <section className="control-column">
          <fieldset className="sender-mode-switch" aria-label="전송 화면 전환">
            <legend>화면 선택</legend>
            <label className="sender-mode-option">
              <input
                checked={senderMode === 'transfer'}
                name="sender-mode"
                onChange={() => handleSetSenderMode('transfer')}
                type="radio"
                value="transfer"
              />
              기본 전송
            </label>
            <label className="sender-mode-option">
              <input
                checked={senderMode === 'bobs'}
                name="sender-mode"
                onChange={() => handleSetSenderMode('bobs')}
                type="radio"
                value="bobs"
              />
              밥스버거
            </label>
          </fieldset>

          <section className="date-card" aria-labelledby="shipment-date-heading">
            <h2 className="date-card-title" id="shipment-date-heading">선적 날짜</h2>
            <div className="date-selects">
              <label>
                연도
                <select value={selectedYear} onChange={(event) => setSelectedYear(Number(event.target.value))}>
                  {yearOptions.map((year) => <option key={year} value={year}>{year}년</option>)}
                </select>
              </label>
              <label>
                월
                <select value={selectedMonth} onChange={(event) => setSelectedMonth(Number(event.target.value))}>
                  {monthOptions.map((month) => <option key={month} value={month}>{month}월</option>)}
                </select>
              </label>
              <label>
                일
                <select value={selectedDay} onChange={(event) => setSelectedDay(Number(event.target.value))}>
                  {dayOptions.map((day) => <option key={day} value={day}>{day}일</option>)}
                </select>
              </label>
            </div>
          </section>

          {senderMode === 'bobs' ? (
            <section className="bobs-card" aria-labelledby="bobs-selector-heading">
              <div className="bobs-card-heading">
                <div>
                  <h2 id="bobs-selector-heading">밥스버거</h2>
                </div>
                <div className="bobs-header-actions" aria-label="밥스버거 전송 작업">
                  <button aria-label="밥스버거 선택 초기화" className="ghost-button" disabled={isBusy} onClick={handleResetBobsSelection} type="button">초기화</button>
                  <button aria-label="선택 목록 전송" className="primary-button" disabled={isNormalSendDisabled} onClick={handleSend} type="button">전송</button>
                  <button aria-label="전송 목록 수정" className="ghost-button" disabled={isRevisionSendDisabled} onClick={() => void handleSendRevision()} type="button">수정전송</button>
                </div>
              </div>

              <fieldset className="bobs-radio-group" aria-label="밥스버거 선택 방식">
                <legend>선택 방식</legend>
                <label className="bobs-radio-option">
                  <input
                    aria-label="SEQ 선택 모드"
                    checked={bobsSelectionMode === 'SEQ'}
                    name="bobs-selection-mode"
                    onChange={() => {
                      clearBobsRetakePdfSelection();
                      setBobsSelectionMode('SEQ');
                    }}
                    type="radio"
                    value="SEQ"
                  />
                  SEQ
                </label>
                <label className="bobs-radio-option">
                  <input
                    aria-label="scene 선택 모드"
                    checked={bobsSelectionMode === 'scene'}
                    name="bobs-selection-mode"
                    onChange={() => {
                      clearBobsRetakePdfSelection();
                      setBobsSelectionMode('scene');
                    }}
                    type="radio"
                    value="scene"
                  />
                  scene
                </label>
                <label className="bobs-number-label">
                  {bobsSelectionMode === 'SEQ' ? 'batch' : 'TK'}
                  <input
                    aria-label={`밥스버거 ${bobsSelectionMode === 'SEQ' ? 'batch' : 'TK'} 번호`}
                    inputMode="numeric"
                    onChange={(event) => setBobsTkNumber(sanitizeDigits(event.target.value))}
                    pattern="[0-9]*"
                    placeholder="숫자"
                    type="text"
                    value={bobsTkNumber}
                  />
                </label>
              </fieldset>

              <div className="bobs-job-select-panel" aria-label={`밥스버거 job 선택 ${selectedBobsJob ? 1 : 0}/${bobsJobs.length}`}>
                <label className="bobs-job-select-label">
                  밥스버거 job
                  <select
                    aria-describedby="bobs-job-meta"
                    disabled={isLoadingBobsJobs || bobsJobs.length === 0}
                    onChange={(event) => handleToggleBobsJob(event.target.value)}
                    value={selectedBobsJob ?? ''}
                  >
                    <option value="">{isLoadingBobsJobs ? 'job 목록 불러오는 중' : 'job 선택'}</option>
                    {bobsJobs.map((job) => <option key={job} value={job}>{job}</option>)}
                  </select>
                </label>
                <p className="bobs-selected-job-meta" id="bobs-job-meta">{selectedBobsJobMeta}</p>
              </div>

              <div className="bobs-panel-grid">
                <section className="bobs-list-panel bobs-detail-panel" aria-labelledby="bobs-detail-panel-heading">
                  <div className="bobs-panel-heading">
                    <h3 id="bobs-detail-panel-heading">{bobsSelectionMode}</h3>
                    <span>{selectedBobsSceneEntries.length} scenes</span>
                  </div>
                  {!selectedBobsJob ? (
                    <p className="bobs-empty-row">위의 job 콤보박스에서 하나를 선택하세요.</p>
                  ) : bobsSelectionMode === 'SEQ' ? (() => {
                    const job = selectedBobsJob;
                    const jobDetail = bobsJobDetailCache[job];
                    const jobDetailError = bobsJobDetailErrors[job];
                    const isLoadingJob = loadingBobsJobDetails.includes(job);
                    const selectedSequences = getSelectedJobValues(selectedBobsSequencesByJob, job);
                    const sequences = jobDetail ? getSortedBobsSequenceKeys(jobDetail.sequences) : [];
                    const enabledSequences = sequences.filter((sequence) => (jobDetail?.sequences[sequence]?.length ?? 0) > 0);
                    return (
                      <>
                        {isLoadingJob && <p className="history-status" role="status">{job} detail을 불러오는 중입니다.</p>}
                        {jobDetailError && <p className="history-status" role="status">{job} detail 오류: {jobDetailError}</p>}
                        {jobDetail && jobDetail.scenes.length === 0 && <p className="history-status" role="status">{job} scene.db에서 scene을 읽지 못했습니다. 상태: {jobDetail.status}</p>}
                        {jobDetail && jobDetail.scenes.length > 0 && sequences.length === 0 && <p className="history-status" role="status">{job}에서 사용할 SEQ가 없습니다.</p>}
                        {sequences.length > 0 && (
                          <div className="bobs-list bobs-nested-list" role="group" aria-label={`${job} SEQ 다중 선택`}>
                            {sequences.map((sequence) => {
                              const sceneCount = jobDetail?.sequences[sequence]?.length ?? 0;
                              const isSelected = selectedSequences.includes(sequence);
                              return (
                                <button
                                  aria-pressed={isSelected}
                                  className={`bobs-list-row${isSelected ? ' active' : ''}`}
                                  disabled={sceneCount === 0}
                                  key={sequence}
                                  onClick={(event) => handleToggleBobsSequence(job, sequence, enabledSequences, event.shiftKey)}
                                  type="button"
                                >
                                  <span className="bobs-row-main"><strong>{sequence}</strong></span>
                                  <span className="bobs-row-meta">{sceneCount} scenes</span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </>
                    );
                  })() : (() => {
                    const job = selectedBobsJob;
                    const jobDetail = bobsJobDetailCache[job];
                    const jobDetailError = bobsJobDetailErrors[job];
                    const isLoadingJob = loadingBobsJobDetails.includes(job);
                    const selectedScenes = getSelectedJobValues(selectedBobsScenesByJob, job);
                    const visibleScenes = jobDetail?.scenes ?? [];
                    return (
                      <>
                        {isLoadingJob && <p className="history-status" role="status">{job} detail을 불러오는 중입니다.</p>}
                        {jobDetailError && <p className="history-status" role="status">{job} detail 오류: {jobDetailError}</p>}
                        {jobDetail && jobDetail.scenes.length === 0 && <p className="history-status" role="status">{job} scene.db에서 scene을 읽지 못했습니다. 상태: {jobDetail.status}</p>}
                        {jobDetail && jobDetail.scenes.length > 0 && (
                          <div className="bobs-list bobs-nested-list" role="group" aria-label={`${job} scene 다중 선택`}>
                            {jobDetail.scenes.map((scene) => {
                              const isSelected = selectedScenes.includes(scene);
                              return (
                                <button
                                  aria-pressed={isSelected}
                                  className={`bobs-list-row${isSelected ? ' active' : ''}`}
                                  key={scene}
                                  onClick={(event) => handleToggleBobsScene(job, scene, visibleScenes, event.shiftKey)}
                                  type="button"
                                >
                                  <span className="bobs-row-main"><strong>{scene}</strong></span>
                                  <span className="bobs-row-meta">scene</span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </>
                    );
                  })()}
                </section>
              </div>

              <div className="bobs-inline-messages">
                {(isLoadingBobsJobs || isLoadingBobsJobDetail) && <p className="history-status" role="status">밥스버거 목록을 불러오는 중입니다.</p>}
                {bobsJobsError && <p className="history-status" role="status">job 목록 오류: {bobsJobsError}</p>}
                {bobsWarningsMessage && <p className="history-diagnostic">{bobsWarningsMessage}</p>}
                {shouldShowStatus && <div className="inline-status-panel" role="status">{status}</div>}
              </div>
            </section>
          ) : (
            <DropZone folderPath={activeManifest && !isBobsManifest(activeManifest) ? activeManifest.source_path : ''} isBusy={isBusy} />
          )}
          {senderMode !== 'bobs' && <section className="transfer-panel" aria-label="전송 작업">
            <div className="transfer-action-row">
              <button aria-label="선택 목록 전송" className="primary-button" disabled={isNormalSendDisabled} onClick={handleSend} type="button">전송</button>
              <button aria-label="전송 목록 수정" className="ghost-button" disabled={isRevisionSendDisabled} onClick={() => void handleSendRevision()} type="button">수정전송</button>
            </div>
            {shouldShowStatus && <div className="inline-status-panel" role="status">{status}</div>}
            {visibleTransferManifests.length > 0 && (
              <div className="queue-list" aria-label="전송 대기 목록">
                {visibleTransferManifests.map((manifest) => {
                  const isActive = activeHistoryManifestId === null && manifest.id === activeManifest?.id;
                  return (
                    <button
                      aria-pressed={isActive}
                      className={`queue-item ${getManifestWorkBackgroundClassName(manifest)}${isActive ? ' active' : ''}`}
                      key={manifest.source_path}
                      onClick={() => handleSelectQueuedManifest(manifest)}
                      type="button"
                    >
                      <strong className={getManifestWorkColorClassName(manifest)}>{getManifestDisplayTitle(manifest)}</strong>
                      <span>{countFiles(manifest.files)}개 파일</span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>}

        </section>

        <section className="history-column sent-history-card" aria-labelledby="sent-history-heading">
          <div className="sent-history-heading-row">
            <div>
              <h2 id="sent-history-heading">이전 전송 기록</h2>
            </div>
            <div className="sent-history-heading-actions">
              <button className="ghost-button history-refresh-button" disabled={isBusy} onClick={() => void refreshSentHistory(false, true)} type="button">새로고침</button>
              <span>{filteredHistoryRows.length}/{sentHistory.length}개 기록</span>
            </div>
          </div>
          <div className="history-filter-selects" aria-label="이전 전송 기록 날짜 필터">
            <label>
              연도
              <select
                value={historyYearFilter}
                onChange={(event) => {
                  setHistoryYearFilter(event.target.value);
                  setHistoryMonthFilter('all');
                  setHistoryDayFilter('all');
                }}
              >
                <option value="all">전체 연도</option>
                {historyYearOptions.map((option) => <option key={option.value} value={option.value}>{option.value}년 ({option.count})</option>)}
              </select>
            </label>
            <label>
              월
              <select
                value={historyMonthFilter}
                onChange={(event) => {
                  setHistoryMonthFilter(event.target.value);
                  setHistoryDayFilter('all');
                }}
              >
                <option value="all">전체 월</option>
                {historyMonthOptions.map((option) => <option key={option.value} value={option.value}>{option.value}월 ({option.count})</option>)}
              </select>
            </label>
            <label>
              날짜
              <select value={historyDayFilter} onChange={(event) => setHistoryDayFilter(event.target.value)}>
                <option value="all">전체 날짜</option>
                {historyDayOptions.map((option) => <option key={option.value} value={option.value}>{option.value}일 ({option.count})</option>)}
              </select>
            </label>
          </div>
          <label className="history-search-label">
            파일명/경로 검색
            <input
              aria-label="이전 전송 기록 파일명 또는 경로 검색"
              onChange={(event) => setHistorySearchQuery(event.target.value)}
              placeholder="파일명 또는 경로 입력"
              type="search"
              value={historySearchQuery}
            />
          </label>
          <div className="sent-history-heading-actions" aria-label="이전 전송 기록 선적 날짜 정렬">
            <button
              aria-pressed={shipmentDateSortOrder === 'newest'}
              className="ghost-button history-refresh-button"
              onClick={() => setShipmentDateSortOrder('newest')}
              type="button"
            >
              선적 날짜 최신순
            </button>
            <button
              aria-pressed={shipmentDateSortOrder === 'oldest'}
              className="ghost-button history-refresh-button"
              onClick={() => setShipmentDateSortOrder('oldest')}
              type="button"
            >
              선적 날짜 오래된순
            </button>
          </div>
          {filteredHistoryRows.length > 0 ? (
            <div className="sent-history-list" aria-label="이전 전송 기록">
              {historyLoadError && <p className="history-status" role="status">이전 기록 오류: {historyLoadError}</p>}
              {filteredHistoryRows.map(({ manifest }) => {
                const isActive = activeHistoryManifestId === manifest.id;
                const actualSentTimestamp = getActualSentTimestamp(manifest);
                const isNew = isTimestampOnLocalDate(actualSentTimestamp, currentLocalDateKey);
                const sourceDateFolderLabel = getManifestDateFolderLabel(manifest);
                const historySearchHighlightQuery = normalizedHistorySearchQuery.raw === '' ? '' : historySearchQuery;
                return (
                  <button
                    aria-pressed={isActive}
                    className={`history-item ${getManifestWorkBackgroundClassName(manifest)}${isActive ? ' active' : ''}${isNew ? ' is-new' : ''}`}
                    key={manifest.id}
                    onClick={() => handleSelectSentHistoryManifest(manifest)}
                    type="button"
                  >
                    {isNew && <span className="history-new-badge">NEW</span>}
                    <span className="history-main">
                      <strong className={getManifestWorkColorClassName(manifest)}>{renderSearchHighlightedText(getManifestDisplayTitle(manifest), historySearchHighlightQuery)}</strong>
                      {historySearchHighlightQuery.trim() !== '' && !isBobsManifest(manifest) && <span className="history-source-path">{renderSearchHighlightedText(manifest.source_path, historySearchHighlightQuery)}</span>}
                      {sourceDateFolderLabel && <span className="history-source-date">선적 날짜 {sourceDateFolderLabel}</span>}
                    </span>
                    <span className="history-meta">
                      <span className="history-count">{countFiles(manifest.files)}개 파일</span>
                      <time dateTime={actualSentTimestamp}>{formatSentTimestamp(actualSentTimestamp)}</time>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="empty history-empty" role={historyLoadError ? 'status' : undefined}>
              <p>{historyEmptyText}</p>
              {historyDiagnosticText && <p className="history-diagnostic">{historyDiagnosticText}</p>}
            </div>
          )}
        </section>

        <section className="contents-column contents-card">
          <div className="card-heading">
            <div>
              <h2 className={activeManifest ? getManifestWorkColorClassName(activeManifest) : 'work-color-default'}>{activeManifest ? renderSearchHighlightedText(activeManifestDisplayTitle, activeHistorySearchQuery) : '전송할 폴더 내용'}</h2>
              {activeManifestDateFolderLabel && <p className="source-date-context">선적 날짜 <strong>{activeManifestDateFolderLabel}</strong></p>}
            </div>
            <span>{activeManifest ? `${countFiles(activeManifest.files)}개 파일` : '대기 중'}</span>
          </div>
          <div className="contents-memo-panel">
            <EditPanel note={note} onNoteChange={setNote} />
          </div>
          <FolderContents backendBaseUrl={senderBackendUrl} shipmentId={activeManifest?.id ?? ''} sourcePath={activeManifest?.source_path ?? ''} files={activeManifest?.files ?? []} defaultExpanded={true} highlightQuery={activeHistorySearchQuery} />
        </section>
      </div>

    </main>
  );
}
