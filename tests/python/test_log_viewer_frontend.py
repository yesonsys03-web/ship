from pathlib import Path


ROOT = Path(__file__).parents[2]
LOG_VIEWER_SRC = ROOT / "apps" / "log-viewer" / "src"


def read_source(relative_path: str) -> str:
    return (LOG_VIEWER_SRC / relative_path).read_text(encoding="utf-8")


def get_css_rule(source: str, selector: str) -> str:
    return source.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_log_viewer_maps_florida_files_inside_date_folder_to_korean_title() -> None:
    app_source = read_source("App.tsx")
    mapped_title_body = app_source.split("function getMappedWorkTitle", 1)[1].split("function getEntryMappedTitle", 1)[0]
    entry_title_body = app_source.split("function getEntryTitle", 1)[1].split("function getHostLabel", 1)[0]
    entry_sources_body = app_source.split("function getEntryMappedTitle", 1)[1].split("function getEntryTitle", 1)[0]

    assert "function getFloridaEpisode" in app_source
    assert "FL_(\\d+)" in app_source
    assert "FL0?(\\d{3})" in app_source
    assert "플로리다 ${floridaEpisode}화" in mapped_title_body
    assert "entry.folder_name" in entry_sources_body
    assert "...(entry.files ?? [])" in entry_sources_body
    assert "entry.source_path" in entry_sources_body
    assert "return mappedTitle" in entry_title_body


def test_log_viewer_search_includes_mapped_florida_title() -> None:
    app_source = read_source("App.tsx")
    search_values_body = app_source.split("function getEntrySearchValues", 1)[1].split("function getEntryVisibleTextValues", 1)[0]

    assert "getEntryMappedTitle(entry)" in search_values_body


def test_log_viewer_work_color_classes_apply_to_titles_and_files_foreground_only() -> None:
    app_source = read_source("App.tsx")
    styles_source = read_source("styles.css")
    color_body = app_source.split("function getWorkColorClassName", 1)[1].split("function getEntryMappedTitle", 1)[0]

    for class_name in ["work-color-hazbin", "work-color-florida", "work-color-bobs", "work-color-koth", "work-color-default"]:
        assert class_name in color_body
        rule = get_css_rule(styles_source, f".{class_name}")
        assert rule.strip().startswith("color: var(--work-color-")
        assert "background" not in rule
        assert "border" not in rule
        assert "box-shadow" not in rule

    assert "function getEntryWorkColorClassName" in app_source
    assert "className={getEntryWorkColorClassName(entry)}" in app_source
    assert "getWorkColorClassName(value)" in app_source


def test_log_viewer_work_background_classes_apply_to_cards_and_file_chips() -> None:
    app_source = read_source("App.tsx")
    styles_source = read_source("styles.css")
    bg_body = app_source.split("function getWorkBackgroundClassName", 1)[1].split("function getEntryMappedTitle", 1)[0]

    assert "replace('work-color-', 'work-bg-')" in bg_body
    assert "function getEntryWorkBackgroundClassName" in app_source
    assert "className={`log-card ${getEntryWorkBackgroundClassName(entry)}`}" in app_source
    assert "className={`file-name-chip ${getWorkColorClassName(value)} ${getWorkBackgroundClassName(value)}`}" in app_source

    for class_name in ["work-bg-hazbin", "work-bg-florida", "work-bg-bobs", "work-bg-koth", "work-bg-default"]:
        rule = get_css_rule(styles_source, f".{class_name}")
        assert rule.strip().startswith("background: var(--work-bg-")
        assert "color: var(--ink)" in rule

    assert ".log-card.work-bg-hazbin" in styles_source
    assert ".file-name-chip.work-bg-bobs" in styles_source


def test_log_viewer_hides_redundant_send_only_checkbox() -> None:
    source = read_source("App.tsx")

    assert "전송한것만 보기" not in source
    assert "showSendOnly" not in source


def test_log_viewer_labels_revision_sends() -> None:
    source = read_source("App.tsx")

    assert "수정 전송" in source


def test_log_viewer_displays_canonical_shipment_date_from_source_folder() -> None:
    source = read_source("App.tsx")
    search_values_body = source.split("function getEntrySearchValues", 1)[1].split("function getEntryVisibleTextValues", 1)[0]
    entry_card_body = source.split("function EntryCard", 1)[1].split("export default function App", 1)[0]

    assert "function getEntryShipmentDateLabel" in source
    assert "const shortYearFirstMatch = value.match(/^(\\d{2})(\\d{2})(\\d{2})$/);" in source
    assert "return `${folderDate.year}_${padDatePart(folderDate.month)}${padDatePart(folderDate.day)}`" in source
    assert "shipmentDateLabel" in search_values_body
    assert "<DetailRow label=\"선적 날짜\" value={shipmentDateLabel}" in entry_card_body
