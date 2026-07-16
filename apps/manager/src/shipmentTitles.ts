import type { ShipmentManifest, ShipmentSummary } from './api';

const bobsSceneSuffix = '.bobs-scene';
const kingOfHillTitle = '킹오브더힐';
const floridaTitle = '플로리다';

export function getPathSegments(path: string) {
  return path.split(/[\\/]+/).filter(Boolean);
}

export function getBasename(path: string) {
  const segments = getPathSegments(path);
  return segments[segments.length - 1] ?? path;
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

function isBobsValue(value: string) {
  return getPathSegments(value).some((segment) => /^(?:bobs|bobs_burgers|bob'?s[_ -]?burgers|fasa\d+)/i.test(segment))
    || /(?:^|[^A-Za-z0-9])(?:bobs|bobs_burgers|bob'?s[_ -]?burgers|fasa\d+)/i.test(value)
    || value.includes('밥스버거');
}

function isFloridaValue(value: string) {
  return getPathSegments(value).some((segment) => /^FL/i.test(segment)) || /^FL/i.test(value);
}

function getBobsJobLabel(value: string) {
  return getPathSegments(value).map((segment) => segment.match(/^(FASA\d+)/i)?.[1].toUpperCase()).find((job) => job !== undefined)
    ?? value.match(/(?:^|[^A-Za-z0-9])(FASA\d+)\b/i)?.[1].toUpperCase()
    ?? '';
}

function getBobsTkLabel(value: string) {
  const tkMatch = value.match(/(?:^|[^A-Za-z0-9])TK[_ -]*(\d+)\b/i);
  return tkMatch ? `TK${tkMatch[1]}` : '';
}

function getBobsBatchLabel(value: string) {
  const batchMatch = value.match(/(?:^|[^A-Za-z0-9])batch[_ -]*(\d+)\b/i);
  return batchMatch ? `batch${batchMatch[1]}` : '';
}

function getBobsLabelLabel(sources: string[]) {
  return sources.map(getBobsBatchLabel).find((label) => label !== '')
    ?? sources.map(getBobsTkLabel).find((label) => label !== '')
    ?? '';
}

function getBobsCountLabelFromValue(value: string) {
  const namedCount = value.match(/(?:^|\s)(\d+)\s*(?:개\s*)?(씬|파일|scenes?|files?)(?=\s|$)/i);
  if (namedCount) {
    const unit = /file/i.test(namedCount[2]) || namedCount[2] === '파일' ? '파일' : '씬';
    return `${namedCount[1]}개 ${unit}`;
  }

  return '';
}

function getBobsSceneCountLabel(manifest: ShipmentManifest) {
  const namedCount = getBobsCountLabelFromValue(manifest.folder_name);
  if (namedCount !== '') {
    return namedCount;
  }

  const fileCount = manifest.files.filter((file) => !file.is_dir).length;
  if (fileCount === 0) {
    return '';
  }

  const sceneCount = manifest.files.filter((file) => !file.is_dir && getBasename(file.path).endsWith(bobsSceneSuffix)).length;
  return `${fileCount}개 ${sceneCount > 0 ? '씬' : '파일'}`;
}

function hasBobsJobLabel(value: string) {
  return getBobsJobLabel(value) !== '';
}

function hasBobsLabelLabel(value: string) {
  return getBobsBatchLabel(value) !== '' || getBobsTkLabel(value) !== '';
}

function buildBobsDisplayTitle(title: string, jobLabel: string, labelLabel: string, countLabel: string) {
  const normalizedTitle = normalizeSummaryLabel(title || '밥스버거');
  const countSuffix = normalizedTitle.match(/\s+\d+개\s+(?:씬|파일)$/)?.[0] ?? '';
  const titleWithoutCount = countSuffix ? normalizedTitle.slice(0, -countSuffix.length).trim() : normalizedTitle;
  const detailParts = [
    jobLabel !== '' && !hasBobsJobLabel(titleWithoutCount) ? jobLabel : '',
    labelLabel !== '' && !hasBobsLabelLabel(titleWithoutCount) ? labelLabel : '',
    countSuffix ? countSuffix.trim() : countLabel,
  ];
  return [titleWithoutCount || '밥스버거', ...detailParts].filter(Boolean).join(' ');
}

function isDateFolderName(name: string) {
  return /^(?:\d{4}_\d{4}|\d{4}_\d{2}\d{2}|\d{2}\d{2}_\d{4}|\d{4})$/.test(name);
}

function getMappedWorkTitle(value: string) {
  const segments = getPathSegments(value);
  const hazbinEpisode = segments.map(getHazbinEpisode).find((episode) => episode !== undefined) ?? getHazbinEpisode(value);
  const floridaEpisode = segments.map(getFloridaEpisode).find((episode) => episode !== undefined) ?? getFloridaEpisode(value);
  const kothEpisode = segments.map(getKothEpisode).find((episode) => episode !== undefined) ?? getKothEpisode(value);

  if (hazbinEpisode) {
    return `헤즈빈호텔 ${hazbinEpisode}화`;
  }

  if (floridaEpisode) {
    return `${floridaTitle} ${floridaEpisode}화`;
  }

  if (isFloridaValue(value)) {
    return floridaTitle;
  }

  if (isBobsValue(value)) {
    return '밥스버거';
  }

  if (kothEpisode) {
    return `${kingOfHillTitle} ${kothEpisode}`;
  }

  if (segments.some((segment) => /^(15|16)/.test(segment)) || /^(15|16)/.test(value)) {
    return kingOfHillTitle;
  }

  if (segments.some((segment) => /^hazbin[_ -]?hotel$/i.test(segment))) {
    return '헤즈빈호텔';
  }

  return '';
}

export function getDisplayFolderName(folderName: string) {
  return getMappedWorkTitle(folderName) || folderName;
}

export function getWorkTitle(path: string) {
  return getMappedWorkTitle(path) || getPathSegments(path)[0] || path;
}

function getBobsManifestDisplayTitle(manifest: ShipmentManifest) {
  const title = manifest.folder_name.trim();
  const sources = [manifest.folder_name, manifest.source_path, ...manifest.files.map((file) => file.path)];
  const jobLabel = sources.map(getBobsJobLabel).find((label) => label !== '') ?? '';
  const tkLabel = sources.map(getBobsTkLabel).find((label) => label !== '') ?? '';
  const labelLabel = getBobsLabelLabel(sources) || tkLabel;
  const countLabel = getBobsSceneCountLabel(manifest)
    || (manifest.files.some((file) => !file.is_dir && getBasename(file.path).endsWith(bobsSceneSuffix))
      ? `${manifest.files.filter((file) => !file.is_dir).length}개 씬`
      : '');

  if (title.startsWith('밥스버거')) {
    const normalizedTitle = normalizeSummaryLabel(title);
    return buildBobsDisplayTitle(normalizedTitle, jobLabel, labelLabel, countLabel);
  }

  return ['밥스버거', jobLabel, labelLabel, countLabel].filter(Boolean).join(' ');
}

export function getManifestDisplayTitle(manifest: ShipmentManifest) {
  const sources = [manifest.folder_name, manifest.source_path, ...manifest.files.map((file) => file.path)];

  if (sources.some(isBobsValue)) {
    return getBobsManifestDisplayTitle(manifest);
  }

  const mappedTitles = sources.map(getMappedWorkTitle).filter((title) => title !== '');
  const mappedTitle = mappedTitles.find((title) => /^헤즈빈호텔 \d+화$/.test(title))
    ?? mappedTitles.find((title) => /^킹오브더힐 (?:15|16)/.test(title))
    ?? mappedTitles[0];
  if (mappedTitle) {
    return mappedTitle;
  }

  if (manifest.folder_name.trim() !== '' && !isDateFolderName(manifest.folder_name)) {
    return manifest.folder_name;
  }

  return getBasename(manifest.source_path) || manifest.folder_name;
}

function normalizeSummaryLabel(label: string) {
  return label.trim()
    .replace(/\b(\d+)\s*scenes?\b/i, '$1개 씬')
    .replace(/\b(\d+)\s*files?\b/i, '$1개 파일')
    .replace(/\s+/g, ' ');
}

function getShipmentNavigationFallbackTitle(summary: ShipmentSummary) {
  const displayTitle = getDisplayFolderName(summary.label);
  const trimmedLabel = summary.label.trim();
  const normalizedLabel = normalizeSummaryLabel(trimmedLabel);
  if (displayTitle === '밥스버거' && normalizedLabel !== '' && normalizedLabel !== displayTitle) {
    const bobsSummaryTitle = getBobsSummaryDisplayTitle(summary);
    if (bobsSummaryTitle === '밥스버거') {
      return normalizedLabel;
    }
    return bobsSummaryTitle;
  }
  return displayTitle;
}

function getBobsSummaryDisplayTitle(summary: ShipmentSummary) {
  const sources = [summary.label];
  const jobLabel = sources.map(getBobsJobLabel).find((label) => label !== '') ?? '';
  const labelLabel = getBobsLabelLabel(sources);
  const countLabel = getBobsCountLabelFromValue(summary.label) || (summary.file_count > 0 ? `${summary.file_count}개 파일` : '');
  return buildBobsDisplayTitle('밥스버거', jobLabel, labelLabel, countLabel);
}

export function getShipmentNavigationTitle(summary: ShipmentSummary, manifest: ShipmentManifest | undefined) {
  return manifest ? getManifestDisplayTitle(manifest) : getShipmentNavigationFallbackTitle(summary);
}

export function shouldLoadManifestForNavigation(summary: ShipmentSummary) {
  return isDateFolderName(summary.label);
}
