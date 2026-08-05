import pytest
import zipfile
import zlib
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from ship_sender.bobs_retake_pdf import (
    BobsRetakeDate,
    find_biff_workbook_retake_rows,
    find_biff_workbook_ship_date,
    find_excel_date_in_text,
    find_xls_retake_rows_in_text,
    parse_bobs_retake_pdf,
    parse_bobs_retake_pdf_bytes,
    parse_bobs_retake_text,
    parse_xls_retake_rows,
    parse_xls_ship_date,
)
from ship_sender import server as sender_server


def get_css_rule(source: str, selector: str) -> str:
    return source.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_parse_bobs_retake_text_normalizes_scene_suffix_for_catalog_matching() -> None:
    result = parse_bobs_retake_text(
        """
        FASA12 Creative Retakes
        Due Date 24/6/26
        Seq 24B Sc 23B Tk 01
        """
    )

    assert result["matched"] is True
    assert {"sequence": "24B", "scene_number": "23", "scene_label": "23B", "tk": "01"} in result["rows"]


def test_parse_bobs_retake_text_preserves_scene_suffix_for_display_label() -> None:
    result = parse_bobs_retake_text(
        """
        FASA12 Creative Retakes
        Due Date 7/8/26
        Seq 21 Sc 05A Tk 02
        """
    )

    assert result["matched"] is True
    assert result["rows"] == [{"sequence": "21", "scene_number": "05", "scene_label": "05A", "tk": "02"}]


def test_parse_bobs_retake_pdf_uses_excel_ship_date_when_pdf_due_date_is_missing(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA12_CreativeRetakes.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n(FASA12 Creative Retakes Seq 21 Sc 05A Tk 02)")
    excel_path = tmp_path / "ship-date.xlsx"
    write_xlsx(excel_path, [["notes", ""], ["선적일", "2026-09-12"]])

    result = parse_bobs_retake_pdf(str(pdf_path), excel_paths=[str(excel_path)])

    assert result["matched"] is True
    assert result["due_date"] == {"year": 2026, "month": 9, "day": 12}
    assert result["rows"] == [{"sequence": "21", "scene_number": "05", "scene_label": "05A", "tk": "02"}]


def test_parse_bobs_retake_pdf_uses_excel_slash_ship_date_as_month_day_year(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA12_CreativeRetakes.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n(FASA12 Creative Retakes Seq 21 Sc 05A Tk 02)")
    excel_path = tmp_path / "ship-date.xlsx"
    write_xlsx(excel_path, [["선적일", "07/08/2026"]])

    result = parse_bobs_retake_pdf(str(pdf_path), excel_paths=[str(excel_path)])

    assert result["matched"] is True
    assert result["due_date"] == {"year": 2026, "month": 7, "day": 8}


def test_parse_bobs_retake_pdf_uses_xls_binary_ship_date_near_label(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA12_CreativeRetakes.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n(FASA12 Creative Retakes Seq 21 Sc 05A Tk 02)")
    excel_path = tmp_path / "ship-date.xls"
    excel_path.write_bytes(b"\xd0\xcf\x11\xe0" + "메모 선적일 07/08/2026".encode("cp949") + b"\x00\x01")

    result = parse_bobs_retake_pdf(str(pdf_path), excel_paths=[str(excel_path)])

    assert result["matched"] is True
    assert result["due_date"] == {"year": 2026, "month": 7, "day": 8}


def test_parse_bobs_retake_pdf_uses_xls_mixed_encoding_date_fallback(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA12_CreativeRetakes.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n(FASA12 Creative Retakes Seq 21 Sc 05A Tk 02)")
    excel_path = tmp_path / "ship-date.xls"
    excel_path.write_bytes(b"\xd0\xcf\x11\xe0" + "선적일".encode("utf-16le") + b"\x00\xffFASA12 Creatives 06/17/2026\x00")

    result = parse_bobs_retake_pdf(str(pdf_path), excel_paths=[str(excel_path)])

    assert result["matched"] is True
    assert result["due_date"] == {"year": 2026, "month": 6, "day": 17}


def test_xls_free_text_date_fallback_ignores_rdf_namespace_metadata() -> None:
    result = find_excel_date_in_text("http://www.w3.org/1999/02/22-rdf-syntax-ns# FASA10 Technical Retakes")

    assert result is None


def test_parse_xls_ship_date_uses_filename_date_instead_of_rdf_namespace_metadata(tmp_path: Path) -> None:
    excel_path = tmp_path / "BB F10_TK2_20260521.xls"
    excel_path.write_bytes(b"\xd0\xcf\x11\xe0" + b"http://www.w3.org/1999/02/22-rdf-syntax-ns#")

    result = parse_xls_ship_date(excel_path)

    assert result is not None
    assert result.to_dict() == {"year": 2026, "month": 5, "day": 21}


def test_parse_bobs_retake_pdf_prefers_fasa11_xls_title_date_over_receipt_ship_label(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA11_Creatives.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n(FASA11 Creatives Seq 16A Sc 01A Tk 02)")
    excel_path = tmp_path / "FASA11_actual_runtime_text.xls"
    excel_path.write_bytes(
        b"\xd0\xcf\x11\xe0"
        + (
            "접수일: 6/4/26 선적일: 06/04/2026 "
            "BIFF serial candidate 46177 "
            "BOB'S BURGERS FASA11 Creatives FASA11 06/17/2026"
        ).encode("cp949")
    )

    result = parse_bobs_retake_pdf(str(pdf_path), excel_paths=[str(excel_path)])

    assert result["matched"] is True
    assert result["due_date"] == {"year": 2026, "month": 6, "day": 17}


def test_parse_xls_ship_date_prefers_fasa11_title_date_over_nearby_receipt_candidates(tmp_path: Path) -> None:
    excel_path = tmp_path / "FASA11_with_receipt_and_title_dates.xls"
    excel_path.write_bytes(
        b"\xd0\xcf\x11\xe0"
        + (
            "선적일: 06/04/2026 접수일: 6/4/26 "
            "BOB'S BURGERS notes "
            "Creatives FASA11 06/17/2026 "
            "TK02 rows 16A 01A 02A"
        ).encode("cp949")
    )

    result = parse_xls_ship_date(excel_path)

    assert result is not None
    assert result.to_dict() == {"year": 2026, "month": 6, "day": 17}


def test_parse_xls_ship_date_prefers_bobs_title_marker_over_biff_label_candidate(monkeypatch, tmp_path: Path) -> None:
    excel_path = tmp_path / "BB F11_Creatives_06042026.xls"

    monkeypatch.setattr(
        "ship_sender.bobs_retake_pdf.parse_xls_biff_ship_date",
        lambda path: (BobsRetakeDate(year=2026, month=6, day=4), True),
    )
    monkeypatch.setattr(
        "ship_sender.bobs_retake_pdf.read_xls_decoded_texts",
        lambda path: ["BOB'S BURGERS notes Creatives FASA11 06/17/2026"],
    )

    result = parse_xls_ship_date(excel_path)

    assert result is not None
    assert result.to_dict() == {"year": 2026, "month": 6, "day": 17}


def test_biff_ship_date_prefers_visible_numeric_ship_date_over_receipt_date() -> None:
    workbook = write_biff_workbook(
        [
            (1, 0, "선적일:"),
            (1, 4, 46163.0),
            (3, 4, 46176.0),
        ]
    )

    result, has_ship_label = find_biff_workbook_ship_date(workbook)

    assert has_ship_label is True
    assert result is not None
    assert result.to_dict() == {"year": 2026, "month": 6, "day": 3}


def test_biff_retake_rows_use_korean_table_headers() -> None:
    workbook = write_biff_workbook(
        [
            (1, 0, "시퀀스"),
            (1, 1, "씬"),
            (1, 2, "Take"),
            (2, 0, 1.0),
            (2, 1, 7.0),
            (2, 2, 2.0),
            (3, 0, "2A"),
            (3, 1, "10A"),
            (3, 2, 1.0),
        ]
    )

    rows = find_biff_workbook_retake_rows(workbook)

    assert [row.to_dict() for row in rows] == [
        {"sequence": "01", "scene_number": "07", "scene_label": "07", "tk": "02"},
        {"sequence": "02A", "scene_number": "10", "scene_label": "10A", "tk": "01"},
    ]


def test_biff_retake_rows_use_english_table_headers() -> None:
    workbook = write_biff_workbook(
        [
            (1, 4, "Seq"),
            (1, 5, "SC"),
            (1, 6, "Tk"),
            (2, 4, 16.0),
            (2, 5, "10A"),
            (2, 6, "2"),
        ]
    )

    rows = find_biff_workbook_retake_rows(workbook)

    assert [row.to_dict() for row in rows] == [
        {"sequence": "16", "scene_number": "10", "scene_label": "10A", "tk": "02"},
    ]


def test_biff_retake_rows_use_formula_string_results_in_legacy_cards() -> None:
    workbook = write_biff_workbook_with_formula_strings(
        [(3, 5, "TAKE"), (3, 7, "SEQ:"), (3, 8, "SC No."), (11, 5, "TAKE"), (11, 7, "SEQ:"), (11, 8, "SC No.")],
        [(1, 1, 2.0), (1, 6, "2A"), (1, 8, 1.0), (9, 1, 1.0), (9, 6, "5A"), (9, 8, "10A")],
    )

    rows = find_biff_workbook_retake_rows(workbook)

    assert [row.to_dict() for row in rows] == [
        {"sequence": "02A", "scene_number": "01", "scene_label": "01", "tk": "02"},
        {"sequence": "05A", "scene_number": "10", "scene_label": "10A", "tk": "01"},
    ]


def test_xls_retake_rows_do_not_use_take_label_as_tk_without_explicit_row_structure() -> None:
    rows = find_xls_retake_rows_in_text(
        "BOB'S BURGERS FASA11 Creative Retakes Take 7 06/04/2026 02A 05A 05B 10A 16A 03A"
    )

    assert rows == []


def test_parse_xls_retake_rows_ignores_ambiguous_take_label_text(tmp_path: Path) -> None:
    excel_path = tmp_path / "ambiguous.xls"
    excel_path.write_bytes(
        b"\xd0\xcf\x11\xe0"
        + "BOB'S BURGERS FASA11 Creative Retakes Take 7 06/04/2026 02A 05A 05B 10A 16A 03A".encode("cp949")
    )

    assert parse_xls_retake_rows(excel_path) == []


def test_parse_xls_retake_rows_keeps_mixed_tk01_tk02_groups(tmp_path: Path) -> None:
    excel_path = tmp_path / "FASA11_mixed_tk_rows.xls"
    excel_path.write_bytes(
        b"\xd0\xcf\x11\xe0"
        + (
            "BOB'S BURGERS FASA11 Creatives Tk 02 06/17/2026 "
            "16A 01A 02A 03A 04A 05A 06A 07A 08A 09A "
            "BOB'S BURGERS FASA11 Creatives Tk 01 06/17/2026 "
            "15A 10A 11A 12A 13A 14A 15B 16B"
        ).encode("cp949")
    )

    rows = parse_xls_retake_rows(excel_path)

    assert len(rows) == 16
    assert [row.to_dict()["tk"] for row in rows].count("02") == 9
    assert [row.to_dict()["tk"] for row in rows].count("01") == 7
    assert rows[0].to_dict() == {"sequence": "16A", "scene_number": "01", "scene_label": "01A", "tk": "02"}
    assert rows[-1].to_dict() == {"sequence": "15A", "scene_number": "16", "scene_label": "16B", "tk": "01"}


def test_sender_frontend_bobs_generated_paths_display_as_bobs_not_king_of_hill() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    folder_contents_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "components" / "FolderContents.tsx").read_text()
    display_folder_name_body = app_source.split("function getDisplayFolderName", 1)[1].split("function getManifestDisplayTitles", 1)[0]
    work_title_body = folder_contents_source.split("function getWorkTitle", 1)[1].split("function getDisplayPath", 1)[0]
    work_title_body_lower = work_title_body.lower()

    assert "밥스버거" in display_folder_name_body
    assert "킹오브더힐" not in display_folder_name_body.split("밥스버거", 1)[1]
    assert "bobs" in work_title_body_lower
    assert "킹오브더힐" not in work_title_body[work_title_body_lower.index("bobs") :]


def test_sender_frontend_fl_paths_display_as_florida_for_date_folder_drops() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    folder_contents_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "components" / "FolderContents.tsx").read_text()
    display_folder_name_body = app_source.split("function getDisplayFolderName", 1)[1].split("function getManifestDisplayTitles", 1)[0]
    manifest_titles_body = app_source.split("function getManifestDisplayTitles", 1)[1].split("function getManifestDisplayTitle", 1)[0]
    work_title_body = folder_contents_source.split("function getWorkTitle", 1)[1].split("function getDisplayPath", 1)[0]

    assert "const floridaTitle = '플로리다'" in app_source
    assert "const floridaTitle = '플로리다'" in folder_contents_source
    assert "function getFloridaEpisode" in app_source
    assert "function getFloridaEpisode" in folder_contents_source
    assert "`${floridaTitle} ${floridaEpisode}화`" in display_folder_name_body
    assert "`${floridaTitle} ${floridaEpisode}화`" in work_title_body
    assert "isFloridaValue" in display_folder_name_body
    assert "return floridaTitle" in display_folder_name_body
    assert "...manifest.files.map((file) => file.path)" in manifest_titles_body
    assert "isFloridaValue" in work_title_body
    assert "return floridaTitle" in work_title_body


def test_sender_frontend_koth_promo_paths_display_specific_episode_title() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    display_folder_name_body = app_source.split("function getDisplayFolderName", 1)[1].split("function getManifestDisplayTitles", 1)[0]
    manifest_titles_body = app_source.split("function getManifestDisplayTitles", 1)[1].split("function getManifestDisplayTitle", 1)[0]

    assert "function getKothEpisode" in app_source
    assert "_PROMO" in app_source
    assert "`${kingOfHillTitle} ${kothEpisode}`" in display_folder_name_body
    assert "^킹오브더힐 (?:15|16)" in manifest_titles_body


def test_sender_frontend_work_color_classes_apply_to_titles_and_files_foreground_only() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    folder_contents_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "components" / "FolderContents.tsx").read_text()
    styles_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "styles.css").read_text()
    app_color_body = app_source.split("function getWorkColorClassName", 1)[1].split("function getManifestWorkColorClassName", 1)[0]
    file_color_body = folder_contents_source.split("function getWorkColorClassName", 1)[1].split("function getDisplayPath", 1)[0]

    for class_name in ["work-color-hazbin", "work-color-florida", "work-color-bobs", "work-color-koth", "work-color-default"]:
        assert class_name in app_color_body
        assert class_name in file_color_body
        rule = get_css_rule(styles_source, f".{class_name}")
        assert rule.strip().startswith("color: var(--work-color-")
        assert "background" not in rule
        assert "border" not in rule
        assert "box-shadow" not in rule

    assert "getManifestWorkColorClassName(manifest)" in app_source
    assert "className={activeManifest ? getManifestWorkColorClassName(activeManifest) : 'work-color-default'}" in app_source
    assert "className={`file-path ${getWorkColorClassName(file.path)}`}" in folder_contents_source


def test_sender_frontend_work_background_classes_apply_to_list_and_file_containers() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    folder_contents_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "components" / "FolderContents.tsx").read_text()
    styles_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "styles.css").read_text()
    app_bg_body = app_source.split("function getWorkBackgroundClassName", 1)[1].split("function getManifestWorkColorClassName", 1)[0]
    file_bg_body = folder_contents_source.split("function getWorkBackgroundClassName", 1)[1].split("function getDisplayPath", 1)[0]

    assert "replace('work-color-', 'work-bg-')" in app_bg_body
    assert "replace('work-color-', 'work-bg-')" in file_bg_body
    assert "getManifestWorkBackgroundClassName(manifest)" in app_source
    assert "className={`queue-item ${getManifestWorkBackgroundClassName(manifest)}${isActive ? ' active' : ''}`}" in app_source
    assert "className={`history-item ${getManifestWorkBackgroundClassName(manifest)}${isActive ? ' active' : ''}${isNew ? ' is-new' : ''}`}" in app_source
    assert "className={`file-row ${isFolder ? 'folder-row' : 'file-entry-row'} ${getWorkBackgroundClassName(file.path)}${isSearchMatch ? ' search-match' : ''}`}" in folder_contents_source

    for class_name in ["work-bg-hazbin", "work-bg-florida", "work-bg-bobs", "work-bg-koth", "work-bg-default"]:
        rule = get_css_rule(styles_source, f".{class_name}")
        assert rule.strip().startswith("background: var(--work-bg-")
        assert "color: var(--ink)" in rule

    assert ".queue-item.work-bg-hazbin" in styles_source
    assert ".history-item.work-bg-bobs" in styles_source
    assert ".file-row.work-bg-koth" in styles_source
    assert ".queue-item.work-bg-hazbin:hover" in styles_source
    assert ".history-item.work-bg-bobs.active" in styles_source
    assert ".history-item.work-bg-bobs.is-new" in styles_source
    assert ".file-row.work-bg-koth.search-match" in styles_source
    assert '.history-item[class*="work-bg-"].is-new.active { color: var(--ink); }' in styles_source
    assert '.history-item[class*="work-bg-"].is-new.active .history-count { color: var(--secondary-action); }' in styles_source


def test_sender_frontend_bobs_mixed_tk_generation_does_not_lock_review_to_first_tk() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    auto_apply_body = app_source.split("const nextBobsManifests = autoBobsGeneratedQueue.manifests", 1)[1].split("}, [activeHistoryManifestId", 1)[0]

    assert "setManifests" in auto_apply_body
    assert "...nextBobsManifests" in auto_apply_body
    assert "setActiveManifestId(nextBobsManifests[0].id)" not in auto_apply_body


def test_sender_frontend_bobs_retake_pdf_remains_tk_while_normal_seq_uses_batch_label() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    batch_manifest_body = app_source.split("function createBobsBatchManifest", 1)[1].split("function createBobsRevisionManifest", 1)[0]
    retake_helper_body = app_source.split("function createBobsRetakePdfManifests", 1)[1].split("function createBobsRetakeReviewManifest", 1)[0]
    auto_queue_body = app_source.split("const autoBobsGeneratedQueue = useMemo", 1)[1].split("useEffect(() =>", 1)[0]
    revision_body = app_source.split("async function handleSendRevision", 1)[1].split("if (isNormalRevisionPending)", 1)[0]

    assert "shipmentKind: 'batch' | 'retake' = 'batch'" in batch_manifest_body
    assert "bobs://${jobDetail.environment}/${jobDetail.job}/${shipmentKind}/${batchKey}" in batch_manifest_body
    assert "bobs:${jobDetail.environment}:${jobDetail.job}:${shipmentKind}:${batchKey}" in batch_manifest_body
    assert ".map(([tk, sceneEntries]) => createBobsBatchManifest(sceneEntries, tk, selectedDate, true, 'TK', 'retake'))" in retake_helper_body
    assert "createBobsBatchManifest(sceneEntries, tk, selectedDate, true, 'batch')" not in retake_helper_body
    assert "labelKind: 'TK' | 'batch' = 'TK'" in app_source
    assert "bobsSelectionMode === 'SEQ' ? 'batch' : 'TK'" in auto_queue_body
    assert "bobsSelectionMode === 'SEQ' ? 'batch' : 'TK'" in revision_body



def test_sender_frontend_normal_revision_drop_detects_changed_same_date_title_history() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    handle_scan_body = app_source.split("async function handleScan", 1)[1].split("function handleClearQueue", 1)[0]
    select_history_body = app_source.split("function handleSelectSentHistoryManifest", 1)[1].split("function handleSetSenderMode", 1)[0]
    drop_listener_body = app_source.split("listenForFolderDrops", 1)[1].split("}, []);", 1)[0]

    assert "function getNormalRevisionMatchKey" in app_source
    assert "function findChangedNormalRevisionSourceManifest" in app_source
    assert "if (dateLabel === '' || displayTitle.trim() === '')" in app_source
    assert "if (replacementKey === null)" in app_source
    assert "getNormalRevisionContentSignature(manifest) !== replacementContentSignature" in app_source
    assert "activeHistoryManifestIdRef.current" in handle_scan_body
    assert "sentHistoryRef.current" in handle_scan_body
    assert "const detectedNormalRevisionSourceManifest = findChangedNormalRevisionSourceManifest(nextManifest, sentHistoryRef.current, selectedYear)" in handle_scan_body
    assert "const normalRevisionSourceManifest = selectedNormalRevisionSourceManifest ?? detectedNormalRevisionSourceManifest" in handle_scan_body
    assert "같은 선적 날짜/제목의 변경된 목록" in handle_scan_body
    assert "activeHistoryManifestIdRef.current = manifest.id" in select_history_body
    assert "handleDroppedPathRef.current(path, excelPaths)" in drop_listener_body
    assert "setPendingNormalRevisionManifestId(revisionManifest.id)" in handle_scan_body
    assert "setManifests([revisionManifest])" in handle_scan_body


def test_sender_frontend_history_active_row_uses_selected_id_directly() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    history_list_body = app_source.split("{filteredHistoryRows.map", 1)[1].split("</button>", 1)[0]

    assert "const isActive = activeHistoryManifestId === manifest.id" in history_list_body
    assert "const isActive = activeHistoryManifest?.id === manifest.id" not in history_list_body


def test_sender_frontend_history_selection_blocks_bobs_auto_generation() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    auto_queue_body = app_source.split("const autoBobsGeneratedQueue = useMemo", 1)[1].split("useEffect(() =>", 1)[0]
    auto_apply_effect = app_source.split("const nextBobsManifests = autoBobsGeneratedQueue.manifests", 1)[0].rsplit("useEffect(() =>", 1)[1]
    select_history_body = app_source.split("function handleSelectSentHistoryManifest", 1)[1].split("function handleSetSenderMode", 1)[0]

    assert "activeHistoryManifestId !== null" in auto_queue_body
    assert "activeHistoryManifestId" in auto_queue_body.split("}, [", 1)[1]
    assert "activeHistoryManifestId !== null" in auto_apply_effect
    assert "activeHistoryManifestId" in app_source.split("const nextBobsManifests = autoBobsGeneratedQueue.manifests", 1)[1].split("]);", 1)[0]
    assert "if (!isBobsManifest(manifest))" in select_history_body
    assert "setSenderMode('transfer')" in select_history_body


def test_sender_frontend_normal_send_disables_until_queue_changes() -> None:
    app_source = (Path(__file__).parents[2] / "apps" / "sender" / "src" / "App.tsx").read_text()
    disabled_body = app_source.split("const queuedManifestsForNormalSend", 1)[1].split("const isRevisionSendDisabled", 1)[0]
    revision_disabled_body = app_source.split("const isRevisionSendDisabled", 1)[1].split("const bobsWarningsMessage", 1)[0]
    send_body = app_source.split("async function handleSend", 1)[1].split("async function handleSendRevision", 1)[0]
    send_queued_body = app_source.split("async function sendQueuedManifests", 1)[1].split("return (", 1)[0]

    assert "function getNormalSendQueueSignature" in app_source
    assert "const [lastNormalSentQueueSignature, setLastNormalSentQueueSignature]" in app_source
    assert "normalSendQueueSignature === lastNormalSentQueueSignature" in disabled_body
    assert "isNormalSendUnchangedSinceLastSend" in disabled_body
    assert "isNormalRevisionPending" in disabled_body
    assert "!hasRevisionContext" in revision_disabled_body
    assert "목록이 바뀌지 않아 다시 전송하지 않습니다." in send_body
    assert "setLastNormalSentQueueSignature(getNormalSendQueueSignature(manifestsToSend))" in send_queued_body


def test_parse_bobs_retake_pdf_prefers_pdf_due_date_over_excel_ship_date(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA12_CreativeRetakes.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n(FASA12 Creative Retakes Due Date 7/8/26 Seq 21 Sc 05A Tk 02)")
    excel_path = tmp_path / "ship-date.xlsx"
    write_xlsx(excel_path, [["선적일", date(2026, 9, 12)]])

    result = parse_bobs_retake_pdf(str(pdf_path), due_date_path=str(excel_path))

    assert result["matched"] is True
    assert result["due_date"] == {"year": 2026, "month": 7, "day": 8}


def test_parse_bobs_retake_text_recognizes_creative_retakes_without_space() -> None:
    result = parse_bobs_retake_text("FASA12 CreativeRetakes Due Date 7/8/26 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is True
    assert result["job"] == "FASA12"


@pytest.mark.parametrize("job", ["BASA01", "CASA13", "DASA01"])
def test_parse_bobs_retake_text_recognizes_older_bobs_asa_prefixes(job: str) -> None:
    result = parse_bobs_retake_text(f"{job} CreativeRetakes Due Date 7/8/26 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is True
    assert result["job"] == job


def test_parse_bobs_retake_text_recognizes_job_title_underscore_separator() -> None:
    result = parse_bobs_retake_text("BASA01_Creative Retakes Due Date 7/8/26 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is True
    assert result["job"] == "BASA01"


@pytest.mark.parametrize("title", ["TechCreativeRetakes", "Tech Creative Retakes"])
def test_parse_bobs_retake_text_recognizes_tech_creative_retakes(title: str) -> None:
    result = parse_bobs_retake_text(f"4ASA15 {title} Due Date 9/17/14 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is True
    assert result["job"] == "4ASA15"
    assert result["due_date"] == {"year": 2014, "month": 9, "day": 17}
    assert result["rows"] == [{"sequence": "09", "scene_number": "02", "scene_label": "02", "tk": "02"}]


@pytest.mark.parametrize("title", ["Technical Retakes", "TechnicalRetakes"])
def test_parse_bobs_retake_text_recognizes_technical_retakes(title: str) -> None:
    result = parse_bobs_retake_text(f"FASA10 {title} Due Date 06/17/2026 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is True
    assert result["job"] == "FASA10"
    assert result["due_date"] == {"year": 2026, "month": 6, "day": 17}


def test_parse_bobs_retake_pdf_uses_filename_to_recognize_tech_creative_retakes(tmp_path) -> None:
    pdf_path = tmp_path / "4ASA15_TechCreativeRetakes_091714.pdf"
    pdf_path.write_bytes(b"%PDF-1.3\n(no parseable retake title text)\n")

    result = parse_bobs_retake_pdf(str(pdf_path))

    assert result["matched"] is False
    assert result["recognized"] is True
    assert result["error"] == "Due Date를 찾지 못했습니다."


def test_parse_bobs_retake_pdf_uses_filename_to_recognize_technical_retakes(tmp_path: Path) -> None:
    pdf_path = tmp_path / "FASA10 Technical Retakes_20260520_1612.pdf"
    pdf_path.write_bytes(b"%PDF-1.3\n(no parseable retake title text)\n")

    result = parse_bobs_retake_pdf(str(pdf_path))

    assert result["matched"] is False
    assert result["recognized"] is True
    assert result["error"] == "Due Date를 찾지 못했습니다."


def test_parse_bobs_retake_pdf_bytes_ignores_invalid_octal_literal_escape() -> None:
    pdf = b"%PDF-1.4\n(FASA12 Creative Retakes Due Date 7/8/26 Seq 09 Sc 02 Tk 02 \\777)"

    result = parse_bobs_retake_pdf_bytes(pdf)

    assert result["matched"] is True
    assert result["rows"] == [{"sequence": "09", "scene_number": "02", "scene_label": "02", "tk": "02"}]


def test_parse_bobs_retake_text_extracts_job_due_date_and_rows() -> None:
    result = parse_bobs_retake_text(
        """
        FASA12 Creative Retakes
        Due Date 7/8/26
        Seq 09 Sc 02 Tk 02
        Seq 09 Sc 03 Tk 01
        """
    )

    assert result["matched"] is True
    assert result["job"] == "FASA12"
    assert result["due_date"] == {"year": 2026, "month": 7, "day": 8}
    assert result["rows"] == [
        {"sequence": "09", "scene_number": "02", "scene_label": "02", "tk": "02"},
        {"sequence": "09", "scene_number": "03", "scene_label": "03", "tk": "01"},
    ]


def test_parse_bobs_retake_pdf_bytes_extracts_flate_text_stream() -> None:
    stream = b"BT (FASA12 Creative Retakes) Tj (Due Date 7/8/26) Tj (Seq 09 Sc 02 Tk 02) Tj ET"
    compressed_stream = zlib.compress(stream)
    pdf = b"%PDF-1.4\n1 0 obj << /Filter /FlateDecode /Length " + str(len(compressed_stream)).encode("ascii") + b" >>\nstream\n" + compressed_stream + b"\nendstream\nendobj"

    result = parse_bobs_retake_pdf_bytes(pdf)

    assert result["matched"] is True
    assert result["job"] == "FASA12"
    assert result["due_date"] == {"year": 2026, "month": 7, "day": 8}
    assert result["rows"] == [{"sequence": "09", "scene_number": "02", "scene_label": "02", "tk": "02"}]


def test_parse_bobs_retake_pdf_bytes_extracts_chrome_skia_tounicode_text() -> None:
    lines = [
        "FASA12 Creative Retakes",
        "Due Date 7/8/26",
        "Seq 09 Sc 02 Tk 02",
    ]
    glyphs = {character: f"{index + 1:02X}" for index, character in enumerate(dict.fromkeys("".join(lines)))}
    bfchar_lines = b"\n".join(
        f"<{glyph}> <{ord(character):04X}>".encode("ascii") for character, glyph in glyphs.items()
    )
    cmap = b"".join([b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<00> <FF>
endcodespacerange
""", f"{len(glyphs)} beginbfchar\n".encode("ascii"), bfchar_lines, b"""
endbfchar
endcmap
CMapName currentdict /CMap defineresource pop
end
end"""])
    text_operators = b"\n".join(
        b"BT /F1 9 Tf " + b" ".join(f"<{glyphs[character]}> Tj".encode("ascii") for character in line) + b" ET"
        for line in lines
    )
    compressed_text = zlib.compress(text_operators)
    pdf = b"".join(
        [
            b"%PDF-1.4\n",
            b"1 0 obj << /Type /Font /Subtype /Type3 /ToUnicode 2 0 R >> endobj\n",
            b"2 0 obj << /Filter /FlateDecode /Length ",
            str(len(zlib.compress(cmap))).encode("ascii"),
            b" >>\nstream\n",
            zlib.compress(cmap),
            b"\nendstream\nendobj\n",
            b"3 0 obj << /Resources << /Font << /F1 1 0 R >> >> /Filter /FlateDecode /Length ",
            str(len(compressed_text)).encode("ascii"),
            b" >>\nstream\n",
            compressed_text,
            b"\nendstream\nendobj\n",
        ]
    )

    result = parse_bobs_retake_pdf_bytes(pdf)

    assert result["matched"] is True
    assert result["job"] == "FASA12"
    assert result["due_date"] == {"year": 2026, "month": 7, "day": 8}
    assert result["rows"] == [{"sequence": "09", "scene_number": "02", "scene_label": "02", "tk": "02"}]


def test_bobs_retake_parser_source_avoids_python39_zip_strict() -> None:
    parser_source = Path(__file__).parents[2] / "python" / "ship_sender" / "bobs_retake_pdf.py"

    assert "strict" + "=" not in parser_source.read_text()


def test_parse_bobs_retake_text_returns_non_match_for_other_pdf_text() -> None:
    result = parse_bobs_retake_text("FASA12 regular shipment Due Date 7/8/26 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is False
    assert result["rows"] == []


def test_parse_bobs_retake_text_rejects_invalid_month_day_date() -> None:
    result = parse_bobs_retake_text("FASA12 Creative Retakes Due Date 31/2/26 Seq 09 Sc 02 Tk 02")

    assert result["matched"] is False
    assert result["due_date"] is None


def test_bobs_retake_pdf_route_returns_parser_payload(monkeypatch) -> None:
    handler = object.__new__(sender_server.SenderHandler)
    handler.path = "/bobs/retake-pdf"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)
    expected = {"matched": True, "job": "FASA12", "due_date": {"year": 2026, "month": 7, "day": 8}, "rows": [], "error": ""}
    sent = {"payload": None, "status": None}

    def fake_read_json(self):
        return {"path": "/tmp/retake.pdf"}

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["payload"] = payload
        sent["status"] = status

    monkeypatch.setattr(sender_server.SenderHandler, "_read_json", fake_read_json)
    monkeypatch.setattr(sender_server.SenderHandler, "_send_json", fake_send_json)
    monkeypatch.setattr(sender_server, "parse_bobs_pdf", lambda path, **kwargs: expected)

    sender_server.SenderHandler.do_POST(handler)

    assert sent == {"payload": expected, "status": 200}


def test_bobs_retake_pdf_route_forwards_optional_excel_paths(monkeypatch) -> None:
    handler = object.__new__(sender_server.SenderHandler)
    handler.path = "/bobs/retake-pdf"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)
    expected = {"matched": False, "recognized": True, "job": "", "due_date": None, "rows": [], "error": "Due Date를 찾지 못했습니다."}
    sent = {"payload": None, "status": None}
    calls = []

    def fake_read_json(self):
        return {"path": "/tmp/retake.pdf", "excel_paths": ["/tmp/a.xlsx"], "due_date_path": "/tmp/b.xlsx"}

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["payload"] = payload
        sent["status"] = status

    def fake_parse_bobs_pdf(path, *, excel_paths=None, due_date_path=None):
        calls.append((path, excel_paths, due_date_path))
        return expected

    monkeypatch.setattr(sender_server.SenderHandler, "_read_json", fake_read_json)
    monkeypatch.setattr(sender_server.SenderHandler, "_send_json", fake_send_json)
    monkeypatch.setattr(sender_server, "parse_bobs_pdf", fake_parse_bobs_pdf)

    sender_server.SenderHandler.do_POST(handler)

    assert calls == [("/tmp/retake.pdf", ["/tmp/a.xlsx"], "/tmp/b.xlsx")]
    assert sent == {"payload": expected, "status": 200}


def write_xlsx(path: Path, rows: list[list[object]]) -> None:
    shared_strings: list[str] = []
    shared_string_indexes: dict[str, int] = {}
    row_xml: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{xlsx_column(column_index)}{row_index}"
            if isinstance(value, (date, datetime)):
                serial = (value.date() if isinstance(value, datetime) else value) - date(1899, 12, 30)
                cells.append(f'<c r="{cell_ref}"><v>{serial.days}</v></c>')
                continue
            text = str(value)
            shared_index = shared_string_indexes.setdefault(text, len(shared_strings))
            if shared_index == len(shared_strings):
                shared_strings.append(text)
            cells.append(f'<c r="{cell_ref}" t="s"><v>{shared_index}</v></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    shared_xml = "".join(f"<si><t>{escape_xml(value)}</t></si>" for value in shared_strings)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared_xml}</sst>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(row_xml)}</sheetData></worksheet>')


def xlsx_column(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def escape_xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_biff_workbook(cells: list[tuple[int, int, str | float]]) -> bytes:
    strings: list[str] = []
    string_indexes: dict[str, int] = {}
    sheet_records: list[bytes] = []
    for row, column, value in cells:
        if isinstance(value, str):
            string_index = string_indexes.setdefault(value, len(strings))
            if string_index == len(strings):
                strings.append(value)
            sheet_records.append(biff_record(0x00FD, struct_pack("<HHHI", row, column, 0, string_index)))
            continue
        sheet_records.append(biff_record(0x027E, struct_pack("<HHHI", row, column, 0, encode_biff_rk(value))))
    sst_body = struct_pack("<II", len(strings), len(strings)) + b"".join(encode_biff_string(value) for value in strings)
    sst_record = biff_record(0x00FC, sst_body)
    return sst_record + b"".join(sheet_records)


def write_biff_workbook_with_formula_strings(
    label_cells: list[tuple[int, int, str]],
    formula_cells: list[tuple[int, int, str | float]],
) -> bytes:
    strings: list[str] = []
    string_indexes: dict[str, int] = {}
    records: list[bytes] = []
    for row, column, value in label_cells:
        string_index = string_indexes.setdefault(value, len(strings))
        if string_index == len(strings):
            strings.append(value)
        records.append(biff_record(0x00FD, struct_pack("<HHHI", row, column, 0, string_index)))
    for row, column, value in formula_cells:
        if isinstance(value, str):
            records.append(biff_record(0x0006, struct_pack("<HHH", row, column, 0) + b"\x00\x00\x00\x00\x00\x00\xff\xff" + (b"\x00" * 16)))
            records.append(biff_record(0x0207, encode_biff_string(value)))
            continue
        records.append(biff_record(0x0006, struct_pack("<HHH", row, column, 0) + struct_pack("<d", value) + (b"\x00" * 16)))
    sst_body = struct_pack("<II", len(strings), len(strings)) + b"".join(encode_biff_string(value) for value in strings)
    return biff_record(0x00FC, sst_body) + b"".join(records)


def biff_record(record_type: int, body: bytes) -> bytes:
    return struct_pack("<HH", record_type, len(body)) + body


def encode_biff_string(value: str) -> bytes:
    encoded = value.encode("utf-16le")
    return struct_pack("<HB", len(value), 1) + encoded


def encode_biff_rk(value: float) -> int:
    low, high = struct_pack_unpack_double(value)
    assert low == 0
    return high


def struct_pack(format_string: str, *values: object) -> bytes:
    import struct

    return struct.pack(format_string, *values)


def struct_pack_unpack_double(value: float) -> tuple[int, int]:
    import struct

    return struct.unpack("<II", struct.pack("<d", value))
