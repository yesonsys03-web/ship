from pathlib import Path


ROOT = Path(__file__).parents[2]
LOG_VIEWER_SRC = ROOT / "apps" / "log-viewer" / "src"


def read_source(relative_path: str) -> str:
    return (LOG_VIEWER_SRC / relative_path).read_text()


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
