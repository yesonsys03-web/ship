import type { ReactElement } from 'react';
import type { ShipmentManifest, ShipmentSummary, ShipmentTree } from '../api';
import { getDisplayFolderName, getShipmentNavigationTitle } from '../shipmentTitles';

type HighlightPart = string | ReactElement;

type FilterOption = {
  value: string;
  label: string;
  count: number;
};

type LeftNavigatorProps = {
  tree: ShipmentTree;
  selectedId: string;
  searchQuery: string;
  selectedYear: string;
  selectedMonth: string;
  selectedDate: string;
  yearOptions: FilterOption[];
  monthOptions: FilterOption[];
  manifestCache: Record<string, ShipmentManifest>;
  newShipmentIds: ReadonlySet<string>;
  resultCount: number;
  totalCount: number;
  hasActiveFilters: boolean;
  onSearchChange: (value: string) => void;
  onYearChange: (value: string) => void;
  onMonthChange: (value: string) => void;
  onDateSelectFromList: (year: string, month: string, day: string) => void;
  onSelect: (shipment: ShipmentSummary) => void;
};

function padDatePart(value: string | number) {
  return value.toString().padStart(2, '0');
}

function getDateKey(year: string, month: string, day: string) {
  return `${year}-${padDatePart(month)}-${padDatePart(day)}`;
}

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

export function LeftNavigator({
  tree,
  selectedId,
  searchQuery,
  selectedYear,
  selectedMonth,
  selectedDate,
  yearOptions,
  monthOptions,
  manifestCache,
  newShipmentIds,
  resultCount,
  totalCount,
  hasActiveFilters,
  onSearchChange,
  onYearChange,
  onMonthChange,
  onDateSelectFromList,
  onSelect,
}: LeftNavigatorProps) {
  return (
    <aside className="navigator">
      <h2>선적 목록</h2>
      <div className="navigator-controls">
        <label className="search-control">
          <span>검색</span>
          <input
            type="search"
            value={searchQuery}
            placeholder="작품, 날짜, 메모, 파일 경로"
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
        <div className="filter-selects">
          <label className="year-select-control">
            <span>연도</span>
            <select aria-label="연도 선택" value={selectedYear} onChange={(event) => onYearChange(event.target.value)}>
              <option value="">전체 연도</option>
              {yearOptions.map((option) => (
                <option value={option.value} key={option.value}>{`${option.label} (${option.count})`}</option>
              ))}
            </select>
          </label>
          <label>
            <span>월</span>
            <select value={selectedMonth} onChange={(event) => onMonthChange(event.target.value)}>
              <option value="">전체 월</option>
              {monthOptions.map((option) => (
                <option value={option.value} key={option.value}>{`${option.label} (${option.count})`}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="result-count">
          {hasActiveFilters ? `검색 결과 ${resultCount}개 / 전체 ${totalCount}개` : `전체 ${totalCount}개`}
        </p>
      </div>
      <div className="navigator-list">
        {tree.years.length === 0 && (
          <p className={hasActiveFilters ? 'empty filtered-empty' : 'empty'}>
            {hasActiveFilters ? '조건에 맞는 선적 기록이 없습니다. 검색어나 날짜를 조정하세요.' : '받은 선적이 없습니다.'}
          </p>
        )}
        {tree.years.map((year) => (
          <section className="year-block" key={year.year}>
            <label className="year-heading-control">
              <span>연도</span>
              <select aria-label={`${year.year}년 목록 연도 선택`} value={year.year} onChange={(event) => onYearChange(event.target.value)}>
                {yearOptions.map((option) => (
                  <option value={option.value} key={option.value}>{`${option.label} (${option.count})`}</option>
                ))}
              </select>
            </label>
            {year.months.map((month) => (
              <div className="month-block" key={`${year.year}-${month.month}`}>
                <strong>{Number(month.month)}월</strong>
                {month.shipments.map((shipment) => {
                  const dayLabel = `${Number(shipment.day)}일`;
                  const dateKey = getDateKey(year.year, month.month, shipment.day);
                  const displayLabel = getDisplayFolderName(shipment.label);
                  const navigationTitle = getShipmentNavigationTitle(shipment, manifestCache[shipment.id]);
                  const supportingLabel = navigationTitle !== displayLabel && displayLabel !== '밥스버거' ? displayLabel : '';
                  const isNewShipment = newShipmentIds.has(shipment.id);
                  return (
                    <div className="nav-row" key={shipment.id}>
                      <button
                        className={dateKey === selectedDate ? 'date-chip active' : 'date-chip'}
                        type="button"
                        onClick={() => {
                          onDateSelectFromList(year.year, month.month, shipment.day);
                          onSelect(shipment);
                        }}
                        aria-pressed={dateKey === selectedDate}
                      >
                        {renderHighlightedText(dayLabel, searchQuery)}
                      </button>
                      <button
                        className={shipment.id === selectedId ? 'nav-item active' : 'nav-item'}
                        type="button"
                        onClick={() => onSelect(shipment)}
                      >
                        <span className="nav-title-line">
                          <em>{renderHighlightedText(navigationTitle, searchQuery)}</em>
                          {isNewShipment && <span className="new-badge" aria-label="새 선적">NEW</span>}
                        </span>
                        <span className="nav-file-count">{renderHighlightedText(`${shipment.file_count}개 파일`, searchQuery)}</span>
                        {supportingLabel && <small>{renderHighlightedText(supportingLabel, searchQuery)}</small>}
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </section>
        ))}
      </div>
    </aside>
  );
}
