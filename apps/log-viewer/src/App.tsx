import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { AuditLogDate, AuditLogEntry, AuditLogReadResult } from './api';
import { listAuditLogDates, readAuditLogEntries } from './api';

const dateFormatter = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'full' });
const timestampFormatter = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

type Summary = {
  totalEntries: number;
  sendCount: number;
  totalFiles: number;
  hostCount: number;
};

type SearchHighlightNavigation = {
  startIndex: number;
  activeMatchIndex: number;
  setMatchElement: (index: number, element: HTMLElement | null) => void;
};

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message.trim() !== '') {
    return error.message;
  }
  return fallback;
}

function isPresent(value: string | undefined): value is string {
  return value !== undefined && value.trim() !== '';
}

function getDisplayDate(dateKey: string) {
  const date = new Date(`${dateKey}T00:00:00`);
  return Number.isNaN(date.getTime()) ? dateKey : dateFormatter.format(date);
}

function formatTimestamp(timestamp: string | undefined) {
  if (!isPresent(timestamp)) {
    return '시간 없음';
  }
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : timestampFormatter.format(date);
}

function getActionLabel(action: string | undefined) {
  if (action === 'revision') {
    return '수정 전송';
  }
  if (action === 'send') {
    return '전송';
  }
  return isPresent(action) ? action : '동작 없음';
}

function getPathSegments(path: string) {
  return path.split(/[\\/]+/).filter(Boolean);
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

function isBobsValue(value: string) {
  return getPathSegments(value).some((segment) => /^(?:bobs|bobs_burgers|bob'?s[_ -]?burgers|fasa\d+)/i.test(segment))
    || /(?:^|[^A-Za-z0-9])(?:bobs|bobs_burgers|bob'?s[_ -]?burgers|fasa\d+)/i.test(value)
    || value.includes('밥스버거');
}

function getMappedWorkTitle(value: string) {
  const segments = getPathSegments(value);
  const hazbinEpisode = segments.map(getHazbinEpisode).find((episode) => episode !== undefined) ?? getHazbinEpisode(value);
  const floridaEpisode = segments.map(getFloridaEpisode).find((episode) => episode !== undefined) ?? getFloridaEpisode(value);

  if (hazbinEpisode) {
    return `헤즈빈호텔 ${hazbinEpisode}화`;
  }
  if (floridaEpisode) {
    return `플로리다 ${floridaEpisode}화`;
  }
  if (isFloridaValue(value)) {
    return '플로리다';
  }
  return '';
}

function getWorkColorClassName(value: string) {
  const mappedTitle = getMappedWorkTitle(value);
  const workTitle = mappedTitle || getPathSegments(value)[0] || value;
  if (value.includes('헤즈빈호텔') || workTitle.startsWith('헤즈빈호텔')) {
    return 'work-color-hazbin';
  }
  if (value.includes('플로리다') || workTitle.startsWith('플로리다')) {
    return 'work-color-florida';
  }
  if (value.includes('밥스버거') || workTitle.startsWith('밥스버거') || isBobsValue(value)) {
    return 'work-color-bobs';
  }
  if (value.includes('킹오브더힐') || workTitle.startsWith('킹오브더힐') || getKothEpisode(value) !== undefined) {
    return 'work-color-koth';
  }
  return 'work-color-default';
}

function getEntryMappedTitle(entry: AuditLogEntry) {
  const sources = [entry.folder_name, ...(entry.files ?? []), entry.source_path].filter((value): value is string => isPresent(value));
  return sources.map(getMappedWorkTitle).find((title) => title !== '') ?? '';
}

function getEntryTitle(entry: AuditLogEntry) {
  const mappedTitle = getEntryMappedTitle(entry);
  if (mappedTitle !== '') {
    return mappedTitle;
  }
  if (isPresent(entry.folder_name)) {
    return entry.folder_name;
  }
  if (isPresent(entry.manifest_id)) {
    return entry.manifest_id;
  }
  if (isPresent(entry.source_path)) {
    return entry.source_path;
  }
  return '제목 없음';
}

function getEntryWorkColorClassName(entry: AuditLogEntry) {
  const sources = [getEntryTitle(entry), entry.folder_name, ...(entry.files ?? []), entry.source_path].filter((value): value is string => isPresent(value));
  return sources.map(getWorkColorClassName).find((className) => className !== 'work-color-default') ?? 'work-color-default';
}

function getHostLabel(entry: AuditLogEntry) {
  const host = isPresent(entry.hostname) ? entry.hostname : '호스트 없음';
  const ip = isPresent(entry.ip) ? entry.ip : 'IP 없음';
  const source = isPresent(entry.hostname_source) ? entry.hostname_source : '출처 없음';
  return `${host} / ${ip} · ${source}`;
}

function getMetaItems(entry: AuditLogEntry) {
  return [
    isPresent(entry.job) ? `job ${entry.job}` : '',
    isPresent(entry.tk) ? `TK ${entry.tk}` : '',
    isPresent(entry.batch) ? `batch ${entry.batch}` : '',
    entry.file_count !== undefined ? `${entry.file_count}개 파일` : '',
  ].filter((item) => item !== '');
}

function getEntryFileNames(entry: AuditLogEntry) {
  return (entry.files ?? []).map((file) => file.trim()).filter((file) => file !== '');
}

function getEntryContentFallback(entry: AuditLogEntry) {
  if (isPresent(entry.note)) {
    return entry.note;
  }
  if (isPresent(entry.folder_name)) {
    return entry.folder_name;
  }
  return entry.manifest_id;
}

function getEntryContentValues(entry: AuditLogEntry) {
  const files = getEntryFileNames(entry);
  if (files.length > 0) {
    return files;
  }
  const fallback = getEntryContentFallback(entry);
  return isPresent(fallback) ? [fallback] : [];
}

function normalizeSearchValue(value: string) {
  return value.trim().toLocaleLowerCase();
}

function countTextMatches(value: string, normalizedQuery: string) {
  if (normalizedQuery === '') {
    return 0;
  }

  const normalizedValue = value.toLocaleLowerCase();
  let count = 0;
  let startIndex = 0;
  let matchIndex = normalizedValue.indexOf(normalizedQuery, startIndex);

  while (matchIndex !== -1) {
    count += 1;
    startIndex = matchIndex + normalizedQuery.length;
    matchIndex = normalizedValue.indexOf(normalizedQuery, startIndex);
  }

  return count;
}

function highlightText(value: string, query: string, navigation?: SearchHighlightNavigation): ReactNode {
  const normalizedQuery = normalizeSearchValue(query);
  if (normalizedQuery === '') {
    return value;
  }

  const normalizedValue = value.toLocaleLowerCase();
  const nodes: ReactNode[] = [];
  let startIndex = 0;
  let markIndex = 0;
  let matchIndex = normalizedValue.indexOf(normalizedQuery, startIndex);

  while (matchIndex !== -1) {
    if (matchIndex > startIndex) {
      nodes.push(value.slice(startIndex, matchIndex));
    }

    const endIndex = matchIndex + normalizedQuery.length;
    const navigationContext = navigation;
    const globalMatchIndex = navigationContext === undefined ? undefined : navigationContext.startIndex + markIndex;
    const isActiveMatch = globalMatchIndex !== undefined && globalMatchIndex === navigationContext?.activeMatchIndex;
    nodes.push(
      <mark
        className={isActiveMatch ? 'search-highlight active' : 'search-highlight'}
        data-search-match-index={globalMatchIndex}
        id={globalMatchIndex === undefined ? undefined : `search-match-${globalMatchIndex}`}
        key={`match-${matchIndex}-${markIndex}`}
        ref={
          globalMatchIndex === undefined || navigationContext === undefined
            ? undefined
            : (element) => navigationContext.setMatchElement(globalMatchIndex, element)
        }
      >
        {value.slice(matchIndex, endIndex)}
      </mark>,
    );

    startIndex = endIndex;
    markIndex += 1;
    matchIndex = normalizedValue.indexOf(normalizedQuery, startIndex);
  }

  if (startIndex < value.length) {
    nodes.push(value.slice(startIndex));
  }

  return nodes.length === 0 ? value : nodes;
}

function getEntrySearchValues(entry: AuditLogEntry) {
  const fileCount = entry.file_count;
  const actionLabel = getActionLabel(entry.action);
  const contentValues = getEntryContentValues(entry);
  return [
    actionLabel,
    actionLabel.replace(/\s+/g, ''),
    entry.action ?? '',
    getEntryTitle(entry),
    getEntryMappedTitle(entry),
    entry.folder_name ?? '',
    entry.manifest_id ?? '',
    entry.source_path ?? '',
    getHostLabel(entry),
    entry.hostname ?? '',
    entry.ip ?? '',
    entry.hostname_source ?? '',
    entry.job ?? '',
    entry.tk ?? '',
    entry.batch ?? '',
    entry.note ?? '',
    ...contentValues,
    ...getEntryFileNames(entry),
    entry.timestamp ?? '',
    formatTimestamp(entry.timestamp),
    entry.date ?? '',
    fileCount === undefined ? '' : String(fileCount),
    fileCount === undefined ? '' : `${fileCount}개 파일`,
    String(entry.line_number),
    `${entry.line_number}번째 줄`,
    ...getMetaItems(entry),
  ].filter((value) => value.trim() !== '');
}

function getEntryVisibleTextValues(entry: AuditLogEntry) {
  return [
    getActionLabel(entry.action),
    getEntryTitle(entry),
    formatTimestamp(entry.timestamp),
    ...getMetaItems(entry),
    getHostLabel(entry),
    ...getEntryContentValues(entry),
    entry.source_path ?? '',
    entry.note ?? '',
  ].filter((value) => value.trim() !== '');
}

function getEntryVisibleMatchCount(entry: AuditLogEntry, normalizedQuery: string) {
  if (normalizedQuery === '') {
    return 0;
  }
  return getEntryVisibleTextValues(entry).reduce((total, value) => total + countTextMatches(value, normalizedQuery), 0);
}

function scrollMatchIntoPanel(matchElement: HTMLElement, contentPanel: HTMLElement) {
  const matchRect = matchElement.getBoundingClientRect();
  const panelRect = contentPanel.getBoundingClientRect();
  const matchCenter = matchRect.top + matchRect.height / 2;
  const panelCenter = panelRect.top + panelRect.height / 2;

  contentPanel.scrollTop += matchCenter - panelCenter;
}

function entryIsTransferLog(entry: AuditLogEntry) {
  return entry.action === 'send' || entry.action === 'revision';
}

function entryMatchesAction(entry: AuditLogEntry) {
  return entryIsTransferLog(entry);
}

function entryMatchesQuery(entry: AuditLogEntry, normalizedQuery: string) {
  if (normalizedQuery === '') {
    return true;
  }
  return getEntrySearchValues(entry).some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
}

function summarize(result: AuditLogReadResult | null): Summary {
  const entries = (result?.entries ?? []).filter(entryIsTransferLog);
  const hosts = new Set(entries.map((entry) => `${entry.hostname ?? ''}/${entry.ip ?? ''}`).filter((value) => value !== '/'));
  return {
    totalEntries: entries.length,
    sendCount: entries.length,
    totalFiles: entries.reduce((total, entry) => total + (entry.file_count ?? 0), 0),
    hostCount: hosts.size,
  };
}

function DetailRow({
  label,
  value,
  renderValue,
}: {
  label: string;
  value: string | undefined;
  renderValue: (value: string) => ReactNode;
}) {
  if (!isPresent(value)) {
    return null;
  }
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>{renderValue(value)}</dd>
    </div>
  );
}

function DetailListRow({
  label,
  values,
  renderValue,
}: {
  label: string;
  values: string[];
  renderValue: (value: string) => ReactNode;
}) {
  if (values.length === 0) {
    return null;
  }
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>
        <span className="file-name-list">
          {values.map((value, index) => (
            <span className={`file-name-chip ${getWorkColorClassName(value)}`} key={`${value}-${index}`}>
              {renderValue(value)}
            </span>
          ))}
        </span>
      </dd>
    </div>
  );
}

function DateButton({ date, selectedDate, onSelect }: { date: AuditLogDate; selectedDate: string; onSelect: (date: string) => void }) {
  return (
    <button
      className={date.date === selectedDate ? 'date-item active' : 'date-item'}
      type="button"
      onClick={() => onSelect(date.date)}
      aria-pressed={date.date === selectedDate}
    >
      <span>{getDisplayDate(date.date)}</span>
      <strong>{date.date}</strong>
    </button>
  );
}

function EntryCard({
  activeMatchIndex,
  entry,
  matchStartIndex,
  query,
  setMatchElement,
}: {
  activeMatchIndex: number;
  entry: AuditLogEntry;
  matchStartIndex: number;
  query: string;
  setMatchElement: (index: number, element: HTMLElement | null) => void;
}) {
  const metaItems = getMetaItems(entry);
  const actionLabel = getActionLabel(entry.action);
  const title = getEntryTitle(entry);
  const timestamp = formatTimestamp(entry.timestamp);
  const contentValues = getEntryContentValues(entry);
  const normalizedQuery = normalizeSearchValue(query);
  let nextMatchStartIndex = matchStartIndex;
  const renderHighlightedValue = (value: string) => {
    const currentMatchStartIndex = nextMatchStartIndex;
    nextMatchStartIndex += countTextMatches(value, normalizedQuery);
    return highlightText(value, query, { activeMatchIndex, setMatchElement, startIndex: currentMatchStartIndex });
  };

  return (
    <article className="log-card">
      <div className="log-card-heading">
        <div>
          <p className="action-chip">{renderHighlightedValue(actionLabel)}</p>
          <h3 className={getEntryWorkColorClassName(entry)}>{renderHighlightedValue(title)}</h3>
        </div>
        <time>{renderHighlightedValue(timestamp)}</time>
      </div>
      {metaItems.length > 0 && (
        <div className="meta-strip">
          {metaItems.map((item) => (
            <span key={item}>{renderHighlightedValue(item)}</span>
          ))}
        </div>
      )}
      <dl className="detail-grid">
        <DetailRow label="호스트/IP" value={getHostLabel(entry)} renderValue={renderHighlightedValue} />
        <DetailListRow label="내용" values={contentValues} renderValue={renderHighlightedValue} />
        <DetailRow label="경로" value={entry.source_path} renderValue={renderHighlightedValue} />
        <DetailRow label="메모" value={entry.note} renderValue={renderHighlightedValue} />
      </dl>
    </article>
  );
}

export default function App() {
  const [dates, setDates] = useState<AuditLogDate[]>([]);
  const [selectedDate, setSelectedDate] = useState('');
  const [result, setResult] = useState<AuditLogReadResult | null>(null);
  const [datesError, setDatesError] = useState('');
  const [entriesError, setEntriesError] = useState('');
  const [isLoadingDates, setIsLoadingDates] = useState(true);
  const [isLoadingEntries, setIsLoadingEntries] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeMatchIndex, setActiveMatchIndex] = useState(0);
  const contentPanelRef = useRef<HTMLElement | null>(null);
  const matchElementsRef = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    let isCurrent = true;

    async function loadDates() {
      setIsLoadingDates(true);
      setDatesError('');
      try {
        const nextDates = await listAuditLogDates();
        if (!isCurrent) {
          return;
        }
        setDates(nextDates);
        setSelectedDate((currentDate) => currentDate || (nextDates[0]?.date ?? ''));
      } catch (error) {
        if (isCurrent) {
          setDatesError(getErrorMessage(error, '전송 로그 날짜를 불러오지 못했습니다.'));
        }
      } finally {
        if (isCurrent) {
          setIsLoadingDates(false);
        }
      }
    }

    loadDates();
    return () => {
      isCurrent = false;
    };
  }, []);

  useEffect(() => {
    let isCurrent = true;

    async function loadEntries() {
      if (selectedDate === '') {
        setResult(null);
        setEntriesError('');
        return;
      }
      setIsLoadingEntries(true);
      setEntriesError('');
      try {
        const nextResult = await readAuditLogEntries(selectedDate);
        if (isCurrent) {
          setResult(nextResult);
        }
      } catch (error) {
        if (isCurrent) {
          setResult(null);
          setEntriesError(getErrorMessage(error, '선택한 날짜의 전송 로그를 읽지 못했습니다.'));
        }
      } finally {
        if (isCurrent) {
          setIsLoadingEntries(false);
        }
      }
    }

    loadEntries();
    return () => {
      isCurrent = false;
    };
  }, [selectedDate]);

  const summary = useMemo(() => summarize(result), [result]);
  const normalizedSearchQuery = useMemo(() => normalizeSearchValue(searchQuery), [searchQuery]);
  const filteredEntries = useMemo(() => {
    const entries = result?.entries ?? [];
    return entries.filter(
      (entry) => entryMatchesAction(entry) && entryMatchesQuery(entry, normalizedSearchQuery),
    );
  }, [normalizedSearchQuery, result]);
  const searchNavigation = useMemo(() => {
    let nextMatchIndex = 0;
    const entries = filteredEntries.map((entry) => {
      const matchStartIndex = nextMatchIndex;
      nextMatchIndex += getEntryVisibleMatchCount(entry, normalizedSearchQuery);
      return { entry, matchStartIndex };
    });
    return { entries, totalMatchCount: nextMatchIndex };
  }, [filteredEntries, normalizedSearchQuery]);
  const { totalMatchCount } = searchNavigation;
  const canNavigateSearchMatches = normalizedSearchQuery !== '' && totalMatchCount > 0;
  const boundedActiveMatchIndex = totalMatchCount === 0 ? 0 : Math.min(activeMatchIndex, totalMatchCount - 1);
  const visibleMatchCounter = canNavigateSearchMatches ? `${boundedActiveMatchIndex + 1} / ${totalMatchCount}` : `0 / ${totalMatchCount}`;
  const hasEntries = summary.totalEntries > 0;
  const hasFilteredOutEntries = hasEntries && filteredEntries.length === 0;
  const selectedDateLabel = selectedDate === '' ? '날짜 없음' : getDisplayDate(selectedDate);
  const setMatchElement = useCallback((index: number, element: HTMLElement | null) => {
    matchElementsRef.current[index] = element;
  }, []);
  const moveSearchMatch = useCallback((direction: 'previous' | 'next') => {
    setActiveMatchIndex((currentIndex) => {
      if (totalMatchCount === 0) {
        return 0;
      }
      if (direction === 'next') {
        return (currentIndex + 1) % totalMatchCount;
      }
      return (currentIndex - 1 + totalMatchCount) % totalMatchCount;
    });
  }, [totalMatchCount]);

  useEffect(() => {
    setActiveMatchIndex(0);
  }, [filteredEntries, normalizedSearchQuery, selectedDate]);

  useEffect(() => {
    matchElementsRef.current.length = totalMatchCount;
  }, [totalMatchCount]);

  useEffect(() => {
    if (totalMatchCount === 0) {
      return;
    }
    const activeMatchElement = matchElementsRef.current[boundedActiveMatchIndex];
    const contentPanel = contentPanelRef.current;
    if (activeMatchElement === undefined || activeMatchElement === null || contentPanel === null) {
      return;
    }
    scrollMatchIntoPanel(activeMatchElement, contentPanel);
  }, [boundedActiveMatchIndex, totalMatchCount]);

  return (
    <main className="log-shell">
      <header className="topbar">
        <div>
          <h1>전송 로그</h1>
          <p className="subtitle">전송 기록을 날짜별로 확인합니다.</p>
        </div>
        <div className="topbar-controls" aria-label="로그 필터와 새로고침">
          <div className="search-field">
            <label htmlFor="log-search-input">로그 검색</label>
            <div className="search-input-row">
              <input
                id="log-search-input"
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.currentTarget.value)}
                placeholder="제목, 경로, PC, TK, 줄번호"
              />
              <div className="search-navigation" aria-label="검색 결과 이동">
                <button
                  aria-label="이전 검색 결과"
                  className="search-nav-button"
                  disabled={!canNavigateSearchMatches}
                  onClick={() => moveSearchMatch('previous')}
                  type="button"
                >
                  ↑
                </button>
                <button
                  aria-label="다음 검색 결과"
                  className="search-nav-button"
                  disabled={!canNavigateSearchMatches}
                  onClick={() => moveSearchMatch('next')}
                  type="button"
                >
                  ↓
                </button>
                {normalizedSearchQuery !== '' && (
                  <span className="search-match-count" aria-live="polite">
                    {visibleMatchCounter}
                  </span>
                )}
              </div>
            </div>
          </div>
          <button className="refresh-button" type="button" onClick={() => window.location.reload()}>
            새로고침
          </button>
        </div>
      </header>

      <section className="workspace">
        <aside className="date-sidebar">
          <div className="sidebar-heading">
            <h2>날짜</h2>
          </div>
          {isLoadingDates && <p className="state-card">날짜를 불러오는 중입니다.</p>}
          {datesError !== '' && <p className="state-card error-state">{datesError}</p>}
          {!isLoadingDates && datesError === '' && dates.length === 0 && (
            <p className="state-card">아직 전송 로그가 없습니다.</p>
          )}
          <div className="date-list">
            {dates.map((date) => (
              <DateButton date={date} selectedDate={selectedDate} onSelect={setSelectedDate} key={date.date} />
            ))}
          </div>
        </aside>

        <section className="content-panel" ref={contentPanelRef}>
          <div className="panel-heading">
            <div>
              <p className="selected-date">{selectedDateLabel}</p>
              <h2>로그 상세</h2>
            </div>
            <div className="summary-grid" aria-label="로그 요약">
              <span><strong>{summary.totalEntries}</strong>건</span>
              <span><strong>{summary.sendCount}</strong>전송</span>
              <span><strong>{summary.totalFiles}</strong>파일</span>
              <span><strong>{summary.hostCount}</strong>호스트</span>
            </div>
          </div>

          {entriesError !== '' && <p className="state-card error-state">{entriesError}</p>}
          {isLoadingEntries && <p className="state-card">선택한 날짜의 로그를 읽는 중입니다.</p>}
          {!isLoadingEntries && entriesError === '' && selectedDate === '' && (
            <p className="empty-panel">왼쪽에서 날짜를 선택하세요.</p>
          )}
          {!isLoadingEntries && entriesError === '' && selectedDate !== '' && result && summary.totalEntries === 0 && (
            <p className="empty-panel">이 날짜의 전송 로그가 없습니다.</p>
          )}
          {!isLoadingEntries && entriesError === '' && hasFilteredOutEntries && (
            <p className="empty-panel">선택한 필터와 검색어에 맞는 로그가 없습니다.</p>
          )}
          {!isLoadingEntries && entriesError === '' && result && result.malformed_count > 0 && (
            <section className="malformed-panel">
              <h3>읽지 못한 줄 {result.malformed_count}개</h3>
              {result.malformed_lines.map((line) => (
                <p key={line.line_number}>
                  {line.line_number}번째 줄 · {line.message}
                </p>
              ))}
            </section>
          )}
          <div className="log-list">
            {searchNavigation.entries.map(({ entry, matchStartIndex }) => (
              <EntryCard
                activeMatchIndex={boundedActiveMatchIndex}
                entry={entry}
                matchStartIndex={matchStartIndex}
                query={searchQuery}
                setMatchElement={setMatchElement}
                key={`${entry.line_number}-${entry.timestamp ?? ''}-${entry.manifest_id ?? ''}`}
              />
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}
