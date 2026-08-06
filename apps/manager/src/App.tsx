import { useEffect, useMemo, useRef, useState } from 'react';
import type { ShipmentManifest, ShipmentSummary, ShipmentTree } from './api';
import { getShipment, listShipments } from './api';
import { notify } from './notifications';
import { ContentPanel } from './components/ContentPanel';
import { LeftNavigator } from './components/LeftNavigator';
import { getDisplayFolderName, getManifestDisplayTitle, getShipmentNavigationTitle, getWorkTitle, shouldLoadManifestForNavigation } from './shipmentTitles';

const EMPTY_TREE: ShipmentTree = { years: [] };

type FilterOption = {
  value: string;
  label: string;
  count: number;
};

type SummaryContext = {
  year: string;
  month: string;
  day: string;
  summary: ShipmentSummary;
  dateKey: string;
};

type SummaryDateParts = {
  year: string;
  month: string;
  day: string;
  dateKey: string;
};

type ShipmentIdSnapshot = Map<string, string>;

type ArrivalNotice = {
  message: string;
};

function padDatePart(value: string | number) {
  return value.toString().padStart(2, '0');
}

function normalizeSearch(value: string) {
  return value.trim().toLocaleLowerCase('ko-KR');
}

function isValidDateParts(year: string, month: string, day: string) {
  const yearNumber = Number(year);
  const monthNumber = Number(month);
  const dayNumber = Number(day);

  if (!Number.isInteger(yearNumber) || !Number.isInteger(monthNumber) || !Number.isInteger(dayNumber)) {
    return false;
  }

  const date = new Date(yearNumber, monthNumber - 1, dayNumber);
  return date.getFullYear() === yearNumber && date.getMonth() === monthNumber - 1 && date.getDate() === dayNumber;
}

function makeSummaryDateParts(year: string, month: string, day: string): SummaryDateParts {
  const paddedMonth = padDatePart(month);
  const paddedDay = padDatePart(day);
  return {
    year,
    month: paddedMonth,
    day: paddedDay,
    dateKey: `${year}-${paddedMonth}-${paddedDay}`,
  };
}

function getLabelDateParts(label: string, yearContext?: string) {
  const yearFirstDate = label.match(/(?:^|_)(\d{4})_(\d{2})(\d{2})(?:_|$)/);
  if (yearFirstDate) {
    const [, year, month, day] = yearFirstDate;
    if (isValidDateParts(year, month, day)) {
      return makeSummaryDateParts(year, month, day);
    }
  }

  const yearLastDate = label.match(/(?:^|_)(\d{2})(\d{2})_(\d{4})(?:_|$)/);

  if (!yearLastDate) {
    const shortYearFirstDate = label.match(/^(\d{2})(\d{2})(\d{2})$/);
    if (shortYearFirstDate) {
      const [, shortYear, month, day] = shortYearFirstDate;
      const baseYear = yearContext === undefined ? new Date().getFullYear() : Number(yearContext);
      const century = baseYear - (baseYear % 100);
      const year = String(century + Number(shortYear));
      return isValidDateParts(year, month, day) ? makeSummaryDateParts(year, month, day) : undefined;
    }

    const bareDate = label.match(/^(\d{2})(\d{2})$/);
    if (!bareDate || yearContext === undefined) {
      return undefined;
    }

    const [, month, day] = bareDate;
    return isValidDateParts(yearContext, month, day) ? makeSummaryDateParts(yearContext, month, day) : undefined;
  }

  const [, month, day, year] = yearLastDate;
  if (!isValidDateParts(year, month, day)) {
    return undefined;
  }

  return makeSummaryDateParts(year, month, day);
}

function getFallbackDateParts(year: string, month: string, summary: ShipmentSummary) {
  const isoDate = summary.created_at.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoDate) {
    return makeSummaryDateParts(isoDate[1], isoDate[2], isoDate[3]);
  }
  return makeSummaryDateParts(year, month, summary.day);
}

function getSummaryDisplayDate(year: string, month: string, summary: ShipmentSummary) {
  return getLabelDateParts(summary.label, year) ?? getFallbackDateParts(year, month, summary);
}

function getDateOptionLabel(dateKey: string, includeYear: boolean) {
  const [year, month, day] = dateKey.split('-');
  const monthDay = `${Number(month)}월 ${padDatePart(day)}일`;
  return includeYear ? `${year}년 ${monthDay}` : monthDay;
}

function getSummaryContexts(tree: ShipmentTree): SummaryContext[] {
  return tree.years.flatMap((year) => year.months.flatMap((month) => month.shipments.map((summary) => {
    const displayDate = getSummaryDisplayDate(year.year, month.month, summary);
    return {
      year: displayDate.year,
      month: displayDate.month,
      day: displayDate.day,
      summary,
      dateKey: displayDate.dateKey,
    };
  })));
}

function getSummaryRecencyTimestamp(summary: ShipmentSummary) {
  const timestamp = new Date(summary.sent_at ?? summary.created_at).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function getFilteredTree(contexts: SummaryContext[], predicate: (context: SummaryContext) => boolean): ShipmentTree {
  const groupedYears = new Map<string, Map<string, ShipmentSummary[]>>();

  contexts
    .filter(predicate)
    .sort((first, second) => {
      const dateDifference = second.dateKey.localeCompare(first.dateKey);
      if (dateDifference !== 0) {
        return dateDifference;
      }
      const recencyDifference = getSummaryRecencyTimestamp(second.summary) - getSummaryRecencyTimestamp(first.summary);
      if (recencyDifference !== 0) {
        return recencyDifference;
      }
      return first.summary.label.localeCompare(second.summary.label, 'ko-KR');
    })
    .forEach((context) => {
    const months = groupedYears.get(context.year) ?? new Map<string, ShipmentSummary[]>();
    const shipments = months.get(context.month) ?? [];
    shipments.push({ ...context.summary, day: context.day });
    months.set(context.month, shipments);
    groupedYears.set(context.year, months);
  });

  return {
    years: Array.from(groupedYears.entries())
      .map(([year, months]) => ({
        year,
        months: Array.from(months.entries())
          .map(([month, shipments]) => ({ month, shipments })),
      }))
  };
}

function matchesDateFilters(context: SummaryContext, selectedYear: string, selectedMonth: string, selectedDate: string) {
  return (selectedYear === '' || context.year === selectedYear)
    && (selectedMonth === '' || context.month === selectedMonth)
    && (selectedDate === '' || context.dateKey === selectedDate);
}

function matchesSummarySearch(context: SummaryContext, searchTerm: string, manifest: ShipmentManifest | undefined) {
  const { summary } = context;
  const haystack = [
    summary.label,
    getDisplayFolderName(summary.label),
    getWorkTitle(summary.label),
    getShipmentNavigationTitle(summary, manifest),
    summary.created_at,
    context.dateKey,
    context.year,
    context.month,
    context.day,
    `${Number(context.month)}월`,
    `${Number(context.day)}일`,
    `${summary.file_count}`,
    `${summary.file_count}개`,
    `${summary.file_count}개 파일`,
  ];
  return haystack.join(' ').toLocaleLowerCase('ko-KR').includes(searchTerm);
}

function matchesManifestSearch(manifest: ShipmentManifest | undefined, searchTerm: string) {
  if (!manifest) {
    return false;
  }

  const haystack = [
    manifest.folder_name,
    getDisplayFolderName(manifest.folder_name),
    getManifestDisplayTitle(manifest),
    getWorkTitle(manifest.folder_name),
    manifest.source_path,
    getWorkTitle(manifest.source_path),
    manifest.note,
    ...manifest.files.flatMap((file) => [file.path, getWorkTitle(file.path)]),
  ];
  return haystack.join(' ').toLocaleLowerCase('ko-KR').includes(searchTerm);
}

function shipmentExists(tree: ShipmentTree, id: string) {
  return tree.years.some((year) => year.months.some((month) => month.shipments.some((shipment) => shipment.id === id)));
}

function getShipmentSignature(summary: ShipmentSummary) {
  return summary.content_signature ?? [summary.created_at, summary.label, summary.file_count].join('\0');
}

function getShipmentSnapshot(tree: ShipmentTree): ShipmentIdSnapshot {
  return new Map(getSummaryContexts(tree).map((context) => [context.summary.id, getShipmentSignature(context.summary)]));
}

function getLocalDateKey(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const year = date.getFullYear();
  const month = (date.getMonth() + 1).toString().padStart(2, '0');
  const day = date.getDate().toString().padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getTodayShipmentIds(tree: ShipmentTree, todayKey: string): string[] {
  return getSummaryContexts(tree)
    .filter((context) => getLocalDateKey(context.summary.sent_at ?? context.summary.created_at) === todayKey)
    .map((context) => context.summary.id);
}

function getNewShipmentIds(previousIds: ShipmentIdSnapshot, nextIds: ShipmentIdSnapshot): string[] {
  return Array.from(nextIds.keys()).filter((id) => !previousIds.has(id));
}

function getChangedExistingShipmentIds(previousIds: ShipmentIdSnapshot, nextIds: ShipmentIdSnapshot, excludedIds: ReadonlySet<string>): string[] {
  return Array.from(nextIds.entries())
    .filter(([id, signature]) => !excludedIds.has(id) && previousIds.has(id) && previousIds.get(id) !== signature)
    .map(([id]) => id);
}

export default function App() {
  const [tree, setTree] = useState<ShipmentTree>(EMPTY_TREE);
  const [selected, setSelected] = useState<ShipmentManifest | null>(null);
  const [selectedSummaryId, setSelectedSummaryId] = useState('');
  const [status, setStatus] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedYear, setSelectedYear] = useState('');
  const [selectedMonth, setSelectedMonth] = useState('');
  const [selectedDate, setSelectedDate] = useState('');
  const [manifestCache, setManifestCache] = useState<Record<string, ShipmentManifest>>({});
  const [newShipmentIds, setNewShipmentIds] = useState<ReadonlySet<string>>(() => new Set());
  const [arrivalNotice, setArrivalNotice] = useState<ArrivalNotice | null>(null);
  const knownShipmentIds = useRef<ShipmentIdSnapshot | null>(null);
  const selectedRef = useRef<ShipmentManifest | null>(null);
  const selectedSummaryIdRef = useRef('');

  const today = useMemo(() => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'full' }).format(new Date()), []);
  const todayKey = useMemo(() => getLocalDateKey(new Date().toISOString()), []);
  const normalizedSearchQuery = useMemo(() => normalizeSearch(searchQuery), [searchQuery]);
  const summaryContexts = useMemo(() => getSummaryContexts(tree), [tree]);

  const yearOptions = useMemo<FilterOption[]>(() => {
    const counts = new Map<string, number>();
    summaryContexts.forEach((context) => counts.set(context.year, (counts.get(context.year) ?? 0) + 1));

    return Array.from(counts.entries())
      .sort(([firstYear], [secondYear]) => Number(secondYear) - Number(firstYear))
      .map(([value, count]) => ({
        value,
        label: `${value}년`,
        count,
      }));
  }, [summaryContexts]);

  const monthOptions = useMemo<FilterOption[]>(() => {
    const counts = new Map<string, number>();
    summaryContexts
      .filter((context) => selectedYear === '' || context.year === selectedYear)
      .forEach((context) => counts.set(context.month, (counts.get(context.month) ?? 0) + 1));

    return Array.from(counts.entries())
      .sort(([firstMonth], [secondMonth]) => Number(firstMonth) - Number(secondMonth))
      .map(([value, count]) => ({
        value,
        label: `${Number(value)}월`,
        count,
      }));
  }, [selectedYear, summaryContexts]);

  const exactDateOptions = useMemo<FilterOption[]>(() => {
    const counts = new Map<string, number>();
    summaryContexts
      .filter((context) => (selectedYear === '' || context.year === selectedYear) && (selectedMonth === '' || context.month === selectedMonth))
      .forEach((context) => counts.set(context.dateKey, (counts.get(context.dateKey) ?? 0) + 1));

    return Array.from(counts.entries()).map(([value, count]) => ({
      value,
      label: getDateOptionLabel(value, selectedYear === ''),
      count,
    }));
  }, [selectedMonth, selectedYear, summaryContexts]);

  const dateFilteredContexts = useMemo(
    () => summaryContexts.filter((context) => matchesDateFilters(context, selectedYear, selectedMonth, selectedDate)),
    [selectedDate, selectedMonth, selectedYear, summaryContexts],
  );

  const filteredTree = useMemo(() => getFilteredTree(summaryContexts, (context) => {
    if (!matchesDateFilters(context, selectedYear, selectedMonth, selectedDate)) {
      return false;
    }

    if (normalizedSearchQuery === '') {
      return true;
    }

    return matchesSummarySearch(context, normalizedSearchQuery, manifestCache[context.summary.id]) || matchesManifestSearch(manifestCache[context.summary.id], normalizedSearchQuery);
  }), [manifestCache, normalizedSearchQuery, selectedDate, selectedMonth, selectedYear, summaryContexts]);

  const filteredCount = useMemo(() => countShipments(filteredTree), [filteredTree]);
  const totalCount = useMemo(() => countShipments(tree), [tree]);
  const hasActiveFilters = searchQuery.trim() !== '' || selectedYear !== '' || selectedMonth !== '' || selectedDate !== '';

  const uncachedSearchIds = useMemo(() => {
    if (normalizedSearchQuery === '') {
      return [];
    }
    return dateFilteredContexts
      .map((context) => context.summary.id)
      .filter((id) => manifestCache[id] === undefined);
  }, [dateFilteredContexts, manifestCache, normalizedSearchQuery]);
  const uncachedSearchIdsKey = useMemo(() => uncachedSearchIds.join('\n'), [uncachedSearchIds]);
  const uncachedNavigationTitleIds = useMemo(() => (
    summaryContexts
      .map((context) => context.summary)
      .filter((summary) => shouldLoadManifestForNavigation(summary) && manifestCache[summary.id] === undefined)
      .map((summary) => summary.id)
  ), [manifestCache, summaryContexts]);
  const uncachedNavigationTitleIdsKey = useMemo(() => uncachedNavigationTitleIds.join('\n'), [uncachedNavigationTitleIds]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  useEffect(() => {
    if (selectedMonth !== '' && !monthOptions.some((option) => option.value === selectedMonth)) {
      setSelectedMonth('');
    }
  }, [monthOptions, selectedMonth]);

  useEffect(() => {
    if (selectedDate !== '' && !exactDateOptions.some((option) => option.value === selectedDate)) {
      setSelectedDate('');
    }
  }, [exactDateOptions, selectedDate]);

  useEffect(() => {
    if (selected && !shipmentExists(tree, selected.id)) {
      selectedSummaryIdRef.current = '';
      setSelectedSummaryId('');
      selectedRef.current = null;
      setSelected(null);
    }
    if (selectedSummaryId !== '' && !shipmentExists(tree, selectedSummaryId)) {
      selectedSummaryIdRef.current = '';
      setSelectedSummaryId('');
    }
  }, [selected, selectedSummaryId, tree]);

  useEffect(() => {
    const idsToLoad = uncachedSearchIdsKey.split('\n').filter(Boolean);
    if (normalizedSearchQuery === '' || idsToLoad.length === 0) {
      return;
    }

    let ignore = false;

    async function cacheSearchManifests() {
      const results = await Promise.allSettled(idsToLoad.map(async (id) => ({ id, manifest: await getShipment(id, { includeSceneValidation: false }) })));

      if (ignore) {
        return;
      }

      const fulfilled = results.filter((result): result is PromiseFulfilledResult<{ id: string; manifest: ShipmentManifest }> => result.status === 'fulfilled');
      if (fulfilled.length > 0) {
        setManifestCache((currentCache) => {
          const nextCache = { ...currentCache };
          fulfilled.forEach((result) => {
            nextCache[result.value.id] = result.value.manifest;
          });
          return nextCache;
        });
      }

      if (results.some((result) => result.status === 'rejected')) {
        setStatus('일부 선적 내용을 검색 캐시에 담지 못했습니다.');
      }
    }

    void cacheSearchManifests();

    return () => {
      ignore = true;
    };
  }, [normalizedSearchQuery, uncachedSearchIdsKey]);

  useEffect(() => {
    const idsToLoad = uncachedNavigationTitleIdsKey.split('\n').filter(Boolean);
    if (idsToLoad.length === 0) {
      return;
    }

    let ignore = false;

    async function cacheNavigationTitleManifests() {
      const results = await Promise.allSettled(idsToLoad.map(async (id) => ({ id, manifest: await getShipment(id, { includeSceneValidation: false }) })));
      if (ignore) {
        return;
      }

      const fulfilled = results.filter((result): result is PromiseFulfilledResult<{ id: string; manifest: ShipmentManifest }> => result.status === 'fulfilled');
      if (fulfilled.length > 0) {
        setManifestCache((currentCache) => {
          const nextCache = { ...currentCache };
          fulfilled.forEach((result) => {
            nextCache[result.value.id] = result.value.manifest;
          });
          return nextCache;
        });
      }
    }

    void cacheNavigationTitleManifests();

    return () => {
      ignore = true;
    };
  }, [uncachedNavigationTitleIdsKey]);

  async function refresh() {
    try {
      const nextTree = await listShipments();
      const previousIds = knownShipmentIds.current;
      const nextIds = getShipmentSnapshot(nextTree);
      const detectedNewShipmentIds = previousIds === null ? [] : getNewShipmentIds(previousIds, nextIds);
      const detectedNewShipmentIdSet = new Set(detectedNewShipmentIds);
      const detectedUpdatedShipmentIds = previousIds === null ? [] : getChangedExistingShipmentIds(previousIds, nextIds, detectedNewShipmentIdSet);
      const todayShipmentIds = getTodayShipmentIds(nextTree, todayKey);
      const currentSelected = selectedRef.current;
      const currentSelectedId = selectedSummaryIdRef.current;
      let refreshedSelected: ShipmentManifest | null | undefined;
      let selectedRefreshError = '';

      if (currentSelectedId !== '') {
        if (shipmentExists(nextTree, currentSelectedId)) {
          try {
            refreshedSelected = await getShipment(currentSelectedId);
          } catch (error) {
            selectedRefreshError = error instanceof Error ? error.message : '선택한 선적 내용을 새로고침하지 못했습니다.';
          }
        } else {
          refreshedSelected = null;
        }
      }

      setTree(nextTree);
      knownShipmentIds.current = nextIds;
      setNewShipmentIds(new Set([...todayShipmentIds, ...detectedNewShipmentIds]));

      if (refreshedSelected !== undefined) {
        if (currentSelectedId !== '' && selectedSummaryIdRef.current !== currentSelectedId) {
          return;
        }
        selectedRef.current = refreshedSelected;
        setSelected(refreshedSelected);
        if (refreshedSelected) {
          selectedSummaryIdRef.current = refreshedSelected.id;
          setSelectedSummaryId(refreshedSelected.id);
          setManifestCache((currentCache) => ({ ...currentCache, [refreshedSelected.id]: refreshedSelected }));
        } else {
          selectedSummaryIdRef.current = '';
          setSelectedSummaryId('');
        }
      }

      if (detectedNewShipmentIds.length > 0 || detectedUpdatedShipmentIds.length > 0) {
        const messageParts = [
          detectedNewShipmentIds.length > 0 ? `새 선적 ${detectedNewShipmentIds.length}건` : '',
          detectedUpdatedShipmentIds.length > 0 ? `수정된 선적 ${detectedUpdatedShipmentIds.length}건` : '',
        ].filter(Boolean);
        const message = `${messageParts.join(', ')}이 도착했습니다.`;
        setArrivalNotice({ message });
        setStatus(selectedRefreshError ? `${selectedRefreshError} ${message}` : message);
        await notify('선적관리', message);
      } else if (selectedRefreshError) {
        setStatus(selectedRefreshError);
      } else {
        setStatus('');
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '선적 목록을 읽지 못했습니다.');
    }
  }

  async function loadSelectedManifestSceneValidation(manifestId: string) {
    try {
      const manifest = await getShipment(manifestId);
      if (selectedSummaryIdRef.current !== manifestId) {
        return;
      }
      selectedRef.current = manifest;
      setSelected(manifest);
      setManifestCache((currentCache) => ({ ...currentCache, [manifest.id]: manifest }));
    } catch (error) {
      if (selectedSummaryIdRef.current === manifestId) {
        setStatus(error instanceof Error ? error.message : '씬 폴더 확인을 완료하지 못했습니다.');
      }
    }
  }

  async function handleSelect(summary: ShipmentSummary) {
    selectedSummaryIdRef.current = summary.id;
    setSelectedSummaryId(summary.id);
    try {
      const manifest = await getShipment(summary.id, { includeSceneValidation: false });
      if (selectedSummaryIdRef.current !== summary.id) {
        return;
      }
      selectedRef.current = manifest;
      setSelected(manifest);
      setManifestCache((currentCache) => ({ ...currentCache, [manifest.id]: manifest }));
      setStatus(`${getManifestDisplayTitle(manifest)} 내용을 표시합니다.`);
      void loadSelectedManifestSceneValidation(manifest.id);
    } catch (error) {
      if (selectedSummaryIdRef.current !== summary.id) {
        return;
      }
      setStatus(error instanceof Error ? error.message : '선적 내용을 읽지 못했습니다.');
    }
  }

  function handleDateSelectFromList(year: string, month: string, day: string) {
    setSelectedYear(year);
    setSelectedMonth(padDatePart(month));
    setSelectedDate(`${year}-${padDatePart(month)}-${padDatePart(day)}`);
  }

  return (
    <main className="manager-shell">
      <header className="topbar">
        <div>
          <h1>선적관리</h1>
          <p>{today}</p>
        </div>
        <button className="refresh-button" type="button" onClick={refresh}>새로고침</button>
      </header>
      <div className="workspace">
        <LeftNavigator
          tree={filteredTree}
          selectedId={selectedSummaryId}
          searchQuery={searchQuery}
          selectedYear={selectedYear}
          selectedMonth={selectedMonth}
          selectedDate={selectedDate}
          yearOptions={yearOptions}
          monthOptions={monthOptions}
          manifestCache={manifestCache}
          newShipmentIds={newShipmentIds}
          resultCount={filteredCount}
          totalCount={totalCount}
          hasActiveFilters={hasActiveFilters}
          onSearchChange={setSearchQuery}
          onYearChange={(value) => {
            setSelectedYear(value);
            setSelectedMonth('');
            setSelectedDate('');
          }}
          onMonthChange={(value) => {
            setSelectedMonth(value);
            setSelectedDate('');
          }}
          onDateSelectFromList={handleDateSelectFromList}
          onSelect={handleSelect}
        />
        <ContentPanel manifest={selected} searchQuery={searchQuery} />
      </div>
      {arrivalNotice && (
        <div className="arrival-alert" role="alert">
          <strong>{arrivalNotice.message}</strong>
          <span>선적관리 목록에 NEW 배지로 표시했습니다.</span>
          <button type="button" onClick={() => setArrivalNotice(null)}>확인</button>
        </div>
      )}
    </main>
  );
}

function countShipments(tree: ShipmentTree): number {
  return tree.years.reduce((yearTotal, year) => yearTotal + year.months.reduce((monthTotal, month) => monthTotal + month.shipments.length, 0), 0);
}
