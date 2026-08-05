import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
MANAGER_SRC = ROOT / "apps" / "manager" / "src"
MANAGER_TAURI = ROOT / "apps" / "manager" / "src-tauri"


def read_source(relative_path: str) -> str:
    return (MANAGER_SRC / relative_path).read_text()


def read_manager_tauri_config() -> dict:
    return json.loads((MANAGER_TAURI / "tauri.conf.json").read_text())


def get_css_rule(source: str, selector: str) -> str:
    return source.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_manager_frontend_removes_unnecessary_english_chrome() -> None:
    visible_sources = [
        read_source("App.tsx"),
        read_source("components/LeftNavigator.tsx"),
        read_source("components/ContentPanel.tsx"),
    ]
    combined_source = "\n".join(visible_sources)

    assert "Shipment Manager" not in combined_source
    assert ">Received<" not in combined_source
    assert ">Detail<" not in combined_source
    assert "선적관리" in visible_sources[0]
    assert "선적 목록" in visible_sources[1]
    assert "선적 상세" in visible_sources[2]


def test_manager_frontend_uses_manifest_cache_for_navigation_titles_after_detail_load() -> None:
    app_source = read_source("App.tsx")
    navigator_source = read_source("components/LeftNavigator.tsx")
    title_source = read_source("shipmentTitles.ts")

    assert "manifestCache={manifestCache}" in app_source
    assert "setManifestCache((currentCache) => ({ ...currentCache, [manifest.id]: manifest }))" in app_source
    assert "getShipmentNavigationTitle(shipment, manifestCache[shipment.id])" in navigator_source
    assert "HH0?(\\d{3})" in title_source
    assert "헤즈빈호텔 ${hazbinEpisode}화" in title_source
    assert "^헤즈빈호텔 \\d+화$" in title_source
    assert "getManifestDisplayTitle(manifest)" in title_source


def test_manager_frontend_fl_files_inside_date_folders_display_as_florida() -> None:
    title_source = read_source("shipmentTitles.ts")
    mapped_title_body = title_source.split("function getMappedWorkTitle", 1)[1].split("export function getDisplayFolderName", 1)[0]
    manifest_title_body = title_source.split("export function getManifestDisplayTitle", 1)[1].split("export function getShipmentNavigationTitle", 1)[0]
    navigation_cache_body = title_source.split("export function shouldLoadManifestForNavigation", 1)[1]

    assert "const floridaTitle = '플로리다'" in title_source
    assert "function isFloridaValue" in title_source
    assert "function getFloridaEpisode" in title_source
    assert "`${floridaTitle} ${floridaEpisode}화`" in mapped_title_body
    assert "isFloridaValue(value)" in mapped_title_body
    assert "return floridaTitle" in mapped_title_body
    assert "...manifest.files.map((file) => file.path)" in manifest_title_body
    assert "sources.map(getMappedWorkTitle)" in manifest_title_body
    assert "isDateFolderName(summary.label)" in navigation_cache_body


def test_manager_frontend_koth_promo_paths_display_specific_episode_title() -> None:
    title_source = read_source("shipmentTitles.ts")
    mapped_title_body = title_source.split("function getMappedWorkTitle", 1)[1].split("export function getDisplayFolderName", 1)[0]
    manifest_title_body = title_source.split("export function getManifestDisplayTitle", 1)[1].split("export function getShipmentNavigationTitle", 1)[0]

    assert "function getKothEpisode" in title_source
    assert "_PROMO" in title_source
    assert "`${kingOfHillTitle} ${kothEpisode}`" in mapped_title_body
    assert "^킹오브더힐 (?:15|16)" in manifest_title_body


def test_manager_frontend_bobs_title_derivation_precedes_king_of_hill_detection() -> None:
    title_source = read_source("shipmentTitles.ts")
    mapped_title_body = title_source.split("function getMappedWorkTitle", 1)[1].split("export function getDisplayFolderName", 1)[0]
    bobs_title_body = title_source.split("function getBobsManifestDisplayTitle", 1)[1].split("export function getManifestDisplayTitle", 1)[0]

    assert mapped_title_body.index("isBobsValue") < mapped_title_body.index("kingOfHillTitle")
    assert "밥스버거" in bobs_title_body
    assert "getBobsTkLabel" in bobs_title_body
    assert "getBobsSceneCountLabel" in bobs_title_body
    assert "개 씬" in bobs_title_body


def test_manager_frontend_work_color_classes_apply_to_titles_and_files_foreground_only() -> None:
    title_source = read_source("shipmentTitles.ts")
    navigator_source = read_source("components/LeftNavigator.tsx")
    content_source = read_source("components/ContentPanel.tsx")
    styles_source = read_source("styles.css")
    color_body = title_source.split("export function getWorkColorClassName", 1)[1].split("function getBobsManifestDisplayTitle", 1)[0]

    for class_name in ["work-color-hazbin", "work-color-florida", "work-color-bobs", "work-color-koth", "work-color-default"]:
        assert class_name in color_body
        rule = get_css_rule(styles_source, f".{class_name}")
        assert rule.strip().startswith("color: var(--work-color-")
        assert "background" not in rule
        assert "border" not in rule
        assert "box-shadow" not in rule

    assert "getWorkColorClassName(navigationTitle)" in navigator_source
    assert "getWorkColorClassName(getManifestDisplayTitle(manifest))" in content_source
    assert "className={`file-path ${getWorkColorClassName(file.path)}`}" in content_source


def test_manager_frontend_work_background_classes_apply_to_nav_and_file_containers() -> None:
    title_source = read_source("shipmentTitles.ts")
    navigator_source = read_source("components/LeftNavigator.tsx")
    content_source = read_source("components/ContentPanel.tsx")
    styles_source = read_source("styles.css")
    bg_body = title_source.split("export function getWorkBackgroundClassName", 1)[1].split("function getBobsManifestDisplayTitle", 1)[0]

    assert "replace('work-color-', 'work-bg-')" in bg_body
    assert "getWorkBackgroundClassName(navigationTitle)" in navigator_source
    assert "className={`nav-item ${getWorkBackgroundClassName(navigationTitle)}${shipment.id === selectedId ? ' active' : ''}`}" in navigator_source
    assert "getWorkBackgroundClassName(file.path)" in content_source
    assert "className={`file-row ${isFolder ? 'folder-row' : 'file-entry-row'} ${getWorkBackgroundClassName(file.path)}`}" in content_source

    for class_name in ["work-bg-hazbin", "work-bg-florida", "work-bg-bobs", "work-bg-koth", "work-bg-default"]:
        rule = get_css_rule(styles_source, f".{class_name}")
        assert rule.strip().startswith("background: var(--work-bg-")
        assert "color: var(--ink)" in rule

    assert ".nav-item.work-bg-hazbin" in styles_source
    assert ".file-row.work-bg-bobs" in styles_source
    assert ".nav-item.work-bg-hazbin:hover" in styles_source
    assert ".nav-item.work-bg-bobs.active" in styles_source


def test_manager_frontend_primary_nav_title_wraps_before_truncating_subtitle() -> None:
    styles_source = read_source("styles.css")
    primary_title_rule = get_css_rule(styles_source, ".nav-item em")
    subtitle_rule = get_css_rule(styles_source, ".nav-item small")

    assert "white-space: normal" in primary_title_rule
    assert "-webkit-line-clamp: 2" in primary_title_rule
    assert "text-overflow: ellipsis" not in primary_title_rule
    assert "white-space: nowrap" not in primary_title_rule
    assert "text-overflow: ellipsis" in subtitle_rule
    assert "white-space: nowrap" in subtitle_rule


def test_manager_frontend_nav_rows_show_korean_file_count_metadata() -> None:
    navigator_source = read_source("components/LeftNavigator.tsx")
    styles_source = read_source("styles.css")
    file_count_rule = get_css_rule(styles_source, ".nav-file-count")
    row_body = navigator_source.split("className={`nav-item ${getWorkBackgroundClassName(navigationTitle)}${shipment.id === selectedId ? ' active' : ''}`}", 1)[1].split("</button>", 1)[0]

    assert 'className="nav-file-count"' in navigator_source
    assert "renderHighlightedText(`${shipment.file_count}개 파일`, searchQuery)" in navigator_source
    assert row_body.index("nav-title-line") < row_body.index("nav-file-count")
    assert row_body.index("nav-file-count") < row_body.index("supportingLabel")
    assert "background: rgba(var(--accent-dark-rgb), 0.1)" in file_count_rule
    assert "color: var(--accent-dark)" in file_count_rule
    assert "font-size: 11px" in file_count_rule


def test_manager_frontend_navigator_list_scrolls_independently_from_controls() -> None:
    navigator_source = read_source("components/LeftNavigator.tsx")
    styles_source = read_source("styles.css")
    navigator_rule = get_css_rule(styles_source, ".navigator")
    controls_rule = get_css_rule(styles_source, ".navigator-controls")
    list_rule = get_css_rule(styles_source, ".navigator-list")

    assert 'className="navigator-list"' in navigator_source
    assert "overflow: hidden" in navigator_rule
    assert "display: flex" in navigator_rule
    assert "flex-direction: column" in navigator_rule
    assert "flex: 0 0 auto" in controls_rule
    assert "overflow-y: auto" in list_rule
    assert "min-height: 0" in list_rule


def test_manager_frontend_year_filter_remains_korean_combo_select() -> None:
    navigator_source = read_source("components/LeftNavigator.tsx")
    styles_source = read_source("styles.css")
    year_select_rule = get_css_rule(styles_source, ".year-select-control select")
    year_heading_rule = get_css_rule(styles_source, ".year-heading-control select")

    assert 'className="year-select-control"' in navigator_source
    assert '<select aria-label="연도 선택" value={selectedYear}' in navigator_source
    assert '<option value="">전체 연도</option>' in navigator_source
    assert 'className="year-heading-control"' in navigator_source
    assert 'aria-label={`${year.year}년 목록 연도 선택`}' in navigator_source
    assert '<h3>{year.year}년</h3>' not in navigator_source
    assert "`${option.label} (${option.count})`" in navigator_source
    assert "appearance: auto" in year_select_rule
    assert "cursor: pointer" in year_select_rule
    assert "font-size: 24px" in year_heading_rule


def test_manager_frontend_refresh_detects_new_shipments_by_id_without_initial_alert() -> None:
    app_source = read_source("App.tsx")
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function handleSelect", 1)[0]

    assert "lastShipmentCount" not in app_source
    assert "const knownShipmentIds = useRef<ShipmentIdSnapshot | null>(null)" in app_source
    assert "type ShipmentIdSnapshot = Map<string, string>" in app_source
    assert "function getShipmentSnapshot(tree: ShipmentTree): ShipmentIdSnapshot" in app_source
    assert "function getNewShipmentIds(previousIds: ShipmentIdSnapshot, nextIds: ShipmentIdSnapshot): string[]" in app_source
    assert "!previousIds.has(id)" in app_source
    assert "const detectedNewShipmentIds = previousIds === null ? [] : getNewShipmentIds(previousIds, nextIds)" in refresh_body
    assert "knownShipmentIds.current = nextIds" in refresh_body
    assert "detectedNewShipmentIds.length > 0" in refresh_body
    assert "새 선적 ${detectedNewShipmentIds.length}건" in refresh_body
    assert "const message = `${messageParts.join(', ')}이 도착했습니다.`" in refresh_body
    assert "setArrivalNotice({ message })" in refresh_body
    assert "await notify('선적관리', message)" in refresh_body
    assert "nextCount > previousCount" not in refresh_body


def test_manager_frontend_refresh_notifies_updated_existing_shipments() -> None:
    app_source = read_source("App.tsx")
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function loadSelectedManifestSceneValidation", 1)[0]

    assert "function getShipmentSignature(summary: ShipmentSummary)" in app_source
    assert "summary.content_signature ?? [summary.created_at, summary.label, summary.file_count].join('\\0')" in app_source
    assert "function getChangedExistingShipmentIds(previousIds: ShipmentIdSnapshot, nextIds: ShipmentIdSnapshot, excludedIds: ReadonlySet<string>): string[]" in app_source
    assert "previousIds.has(id) && previousIds.get(id) !== signature" in app_source
    assert "const detectedUpdatedShipmentIds = previousIds === null ? [] : getChangedExistingShipmentIds(previousIds, nextIds, detectedNewShipmentIdSet)" in refresh_body
    assert "detectedNewShipmentIds.length > 0 || detectedUpdatedShipmentIds.length > 0" in refresh_body
    assert "수정된 선적 ${detectedUpdatedShipmentIds.length}건" in refresh_body


def test_manager_frontend_refresh_never_counts_new_shipments_as_updated() -> None:
    app_source = read_source("App.tsx")
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function loadSelectedManifestSceneValidation", 1)[0]

    assert "function getChangedExistingShipmentIds(previousIds: ShipmentIdSnapshot, nextIds: ShipmentIdSnapshot, excludedIds: ReadonlySet<string>): string[]" in app_source
    assert "!excludedIds.has(id)" in app_source
    assert "const detectedNewShipmentIdSet = new Set(detectedNewShipmentIds)" in refresh_body
    assert "getChangedExistingShipmentIds(previousIds, nextIds, detectedNewShipmentIdSet)" in refresh_body


def test_manager_frontend_successful_refresh_clears_stale_load_failure_status() -> None:
    app_source = read_source("App.tsx")
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function handleSelect", 1)[0]

    assert "setStatus(error instanceof Error ? error.message : '선적 목록을 읽지 못했습니다.')" in refresh_body
    assert "} else {\n        setStatus('');\n      }" in refresh_body


def test_manager_frontend_new_badge_stays_for_today_and_selection_does_not_clear_it() -> None:
    app_source = read_source("App.tsx")
    navigator_source = read_source("components/LeftNavigator.tsx")
    styles_source = read_source("styles.css")
    badge_rule = get_css_rule(styles_source, ".new-badge")
    select_body = app_source.split("async function handleSelect", 1)[1].split("function handleDateSelectFromList", 1)[0]

    assert "const [newShipmentIds, setNewShipmentIds] = useState<ReadonlySet<string>>" in app_source
    assert "function getTodayShipmentIds" in app_source
    assert "context.summary.sent_at ?? context.summary.created_at" in app_source
    assert "newShipmentIds={newShipmentIds}" in app_source
    assert "removeNewShipmentId" not in app_source
    assert "setNewShipmentIds" not in select_body
    assert "newShipmentIds: ReadonlySet<string>" in navigator_source
    assert "const isNewShipment = newShipmentIds.has(shipment.id)" in navigator_source
    assert 'className="new-badge" aria-label="새 선적">NEW</span>' in navigator_source
    assert "background: var(--highlight)" in badge_rule
    assert "color: var(--highlight-ink)" in badge_rule


def test_manager_frontend_selection_feedback_updates_before_detail_fetch_finishes() -> None:
    app_source = read_source("App.tsx")
    select_body = app_source.split("async function handleSelect", 1)[1].split("function handleDateSelectFromList", 1)[0]

    assert "const [selectedSummaryId, setSelectedSummaryId] = useState('')" in app_source
    assert "const selectedSummaryIdRef = useRef('')" in app_source
    assert "selectedSummaryIdRef.current = summary.id" in select_body
    assert select_body.index("selectedSummaryIdRef.current = summary.id") < select_body.index("await getShipment(summary.id, { includeSceneValidation: false })")
    assert "setSelectedSummaryId(summary.id)" in select_body
    assert "if (selectedSummaryIdRef.current !== summary.id)" in select_body
    assert "selectedId={selectedSummaryId}" in app_source
    assert "selectedId={selected?.id ?? ''}" not in app_source


def test_manager_frontend_date_chip_selects_the_matching_shipment() -> None:
    navigator_source = read_source("components/LeftNavigator.tsx")
    date_chip_body = navigator_source.split("className={dateKey === selectedDate ? 'date-chip active' : 'date-chip'}", 1)[1].split("aria-pressed={dateKey === selectedDate}", 1)[0]

    assert "onDateSelectFromList(year.year, month.month, shipment.day)" in date_chip_body
    assert "onSelect(shipment)" in date_chip_body
    assert date_chip_body.index("onDateSelectFromList(year.year, month.month, shipment.day)") < date_chip_body.index("onSelect(shipment)")


def test_manager_frontend_scene_validation_load_is_deferred_and_guarded_by_immediate_selection() -> None:
    app_source = read_source("App.tsx")
    scene_validation_body = app_source.split("async function loadSelectedManifestSceneValidation", 1)[1].split("async function handleSelect", 1)[0]
    select_body = app_source.split("async function handleSelect", 1)[1].split("function handleDateSelectFromList", 1)[0]

    assert "const manifest = await getShipment(manifestId)" in scene_validation_body
    assert "if (selectedSummaryIdRef.current !== manifestId)" in scene_validation_body
    assert "selectedSummaryIdRef.current?.id" not in scene_validation_body
    assert "await getShipment(summary.id, { includeSceneValidation: false })" in select_body
    assert "void loadSelectedManifestSceneValidation(manifest.id)" in select_body


def test_manager_frontend_refresh_reloads_selected_manifest_with_scene_validation() -> None:
    app_source = read_source("App.tsx")
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function loadSelectedManifestSceneValidation", 1)[0]

    assert "mergeFastRefreshManifest" not in app_source
    assert "const currentSelectedId = selectedSummaryIdRef.current" in refresh_body
    assert "refreshedSelected = await getShipment(currentSelectedId)" in refresh_body
    assert "if (currentSelectedId !== '' && selectedSummaryIdRef.current !== currentSelectedId)" in refresh_body
    assert "refreshedSelected = await getShipment(currentSelectedId, { includeSceneValidation: false })" not in refresh_body
    assert "void loadSelectedManifestSceneValidation(refreshedSelected.id)" not in refresh_body


def test_manager_frontend_arrival_alert_persists_separately_from_status_toast() -> None:
    app_source = read_source("App.tsx")
    styles_source = read_source("styles.css")
    alert_rule = get_css_rule(styles_source, ".arrival-alert")

    assert "const [arrivalNotice, setArrivalNotice] = useState<ArrivalNotice | null>(null)" in app_source
    assert 'className="arrival-alert" role="alert"' in app_source
    assert "선적관리 목록에 NEW 배지로 표시했습니다." in app_source
    assert "setArrivalNotice(null)" in app_source
    assert "position: fixed" in alert_rule
    assert "top: 34px" in alert_rule


def test_manager_frontend_arrival_alert_is_large_red_warning() -> None:
    styles_source = read_source("styles.css")
    alert_rule = get_css_rule(styles_source, ".arrival-alert")
    alert_title_rule = get_css_rule(styles_source, ".arrival-alert strong")
    alert_body_rule = get_css_rule(styles_source, ".arrival-alert span")
    alert_button_rule = get_css_rule(styles_source, ".arrival-alert button")

    assert "width: min(460px, calc(100vw - 68px))" in alert_rule
    assert "border: 4px solid #8b1111" in alert_rule
    assert "linear-gradient(135deg, #d71920, #9f1418)" in alert_rule
    assert "padding: 24px 28px" in alert_rule
    assert "font-size: 24px" in alert_title_rule
    assert "font-size: 16px" in alert_body_rule
    assert "color: #8b1111" in alert_button_rule


def test_manager_frontend_sorts_navigation_by_shipment_date_before_transfer_recency() -> None:
    app_source = read_source("App.tsx")
    filtered_tree_body = app_source.split("function getFilteredTree", 1)[1].split("function matchesDateFilters", 1)[0]

    assert "function getSummaryRecencyTimestamp(summary: ShipmentSummary)" in app_source
    assert "summary.sent_at ?? summary.created_at" in app_source
    assert ".sort((first, second) =>" in filtered_tree_body
    assert filtered_tree_body.index("const dateDifference = second.dateKey.localeCompare(first.dateKey)") < filtered_tree_body.index("const recencyDifference = getSummaryRecencyTimestamp(second.summary) - getSummaryRecencyTimestamp(first.summary)")
    assert "getSummaryRecencyTimestamp(second.summary) - getSummaryRecencyTimestamp(first.summary)" in filtered_tree_body
    assert ".sort(([firstYear], [secondYear])" not in filtered_tree_body
    assert ".sort(([firstMonth], [secondMonth])" not in filtered_tree_body


def test_manager_frontend_notification_uses_tauri_plugin_without_internal_window_gate() -> None:
    notification_source = read_source("notifications.ts")

    assert "@tauri-apps/plugin-notification" in notification_source
    assert "__TAURI_INTERNALS__" not in notification_source
    assert "isPermissionGranted()" in notification_source
    assert "requestPermission()" in notification_source
    assert "sendNotification({ title, body })" in notification_source
    assert "console.warn('macOS notification skipped', error)" in notification_source


def test_manager_frontend_does_not_render_bottom_right_status_toast() -> None:
    app_source = read_source("App.tsx")
    styles_source = read_source("styles.css")

    assert "StatusToast" not in app_source
    assert not (MANAGER_SRC / "components" / "StatusToast.tsx").exists()
    assert "const [status, setStatus] = useState('')" in app_source
    assert "setStatus(" in app_source
    assert "status-toast" not in app_source
    assert ".status-toast" not in styles_source


def test_manager_frontend_topbar_uses_compact_header_spacing() -> None:
    styles_source = read_source("styles.css")
    shell_rule = get_css_rule(styles_source, ".manager-shell")
    topbar_rule = get_css_rule(styles_source, ".topbar")
    title_rule = get_css_rule(styles_source, ".topbar h1")
    date_rule = get_css_rule(styles_source, ".topbar p")

    assert "--shell-pad: 18px" in styles_source
    assert "--shell-gap: 14px" in styles_source
    assert "--topbar-pad-bottom: 10px" in styles_source
    assert "--topbar-title-size: 42px" in styles_source
    assert "padding: var(--shell-pad)" in shell_rule
    assert "gap: var(--shell-gap)" in shell_rule
    assert "padding-bottom: var(--topbar-pad-bottom)" in topbar_rule
    assert "font-size: var(--topbar-title-size)" in title_rule
    assert "margin: 0" in title_rule
    assert "line-height: 1" in title_rule
    assert "margin: 0" in date_rule


def test_manager_tauri_window_opens_larger_by_default() -> None:
    window_config = read_manager_tauri_config()["app"]["windows"][0]

    assert window_config["width"] == 1680
    assert window_config["height"] == 920
    assert window_config["minWidth"] == 1320
    assert window_config["minHeight"] == 760


def test_manager_tauri_backend_stops_only_when_app_exits() -> None:
    main_source = (MANAGER_TAURI / "src" / "main.rs").read_text()
    run_body = main_source.split(".run(|app_handle, event|", 1)[1]

    assert ".sidecar(\"ship-manager-backend\")" in main_source
    assert "tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit =>" in run_body
    assert "stop_backend(app_handle)" in run_body
    assert "CloseRequested" not in main_source


def test_manager_frontend_workspace_allocates_more_width_to_content_panel() -> None:
    styles_source = read_source("styles.css")
    workspace_rule = get_css_rule(styles_source, ".workspace")

    assert "body { margin: 0; min-width: 1280px" in styles_source
    assert "grid-template-columns: 360px minmax(820px, 1fr)" in workspace_rule
    assert "gap: 24px" in workspace_rule


def test_manager_frontend_types_backend_scene_validation_on_file_entries() -> None:
    api_source = read_source("api.ts")
    scene_validation_type = api_source.split("export type SceneValidation", 1)[1].split("export type FileEntry", 1)[0]
    file_entry_type = api_source.split("export type FileEntry", 1)[1].split("export type ShipmentManifest", 1)[0]

    assert "checked: boolean" in scene_validation_type
    assert "exists: boolean" in scene_validation_type
    assert "expected_folder_name: string" in scene_validation_type
    assert "matched_path: string | null" in scene_validation_type
    assert "reason: string" in scene_validation_type
    assert "scene_validation?: SceneValidation" in file_entry_type


def test_manager_frontend_bobs_scene_suffix_is_hidden_only_in_visible_labels() -> None:
    content_source = read_source("components/ContentPanel.tsx")
    display_name_body = content_source.split("function getDisplayFileName", 1)[1].split("function getPreviewKind", 1)[0]
    row_body = content_source.split("visibleRows.map((row)", 1)[1].split("return (", 1)[0]
    visible_row_markup = content_source.split("return (", 2)[2]

    assert "const bobsSceneSuffix = '.bobs-scene'" in content_source
    assert "name.endsWith(bobsSceneSuffix)" in display_name_body
    assert "name.slice(0, -bobsSceneSuffix.length)" in display_name_body
    assert "const basename = getBasename(path)" in content_source
    assert "const displayFileName = getDisplayFileName(basename)" in content_source
    assert "workTitle === basename || workTitle === displayFileName ? displayFileName" in content_source
    assert "row.depth === 0 ? getDisplayPath(file.path) : isFolder ? row.name : getDisplayFileName(row.name)" in row_body
    assert "row.childFileNames.map(getDisplayFileName)" in content_source
    assert "key={row.path}" in visible_row_markup
    assert "getFilePreview(manifest.id, manifest.source_path, file)" in row_body


def test_manager_frontend_scene_validation_indicator_has_accessible_korean_states() -> None:
    content_source = read_source("components/ContentPanel.tsx")
    indicator_body = content_source.split("{sceneValidation && (", 1)[1].split(")}", 1)[0]

    assert "const sceneValidation = !isFolder ? file.scene_validation : undefined" in content_source
    assert "scene-validation-pill" in indicator_body
    assert "scene-validation-pill-valid" in indicator_body
    assert "scene-validation-pill-missing" in indicator_body
    assert "씬 폴더 확인됨" in indicator_body
    assert "씬 폴더 없음" in indicator_body
    assert "확인됨" in indicator_body
    assert "없음" in indicator_body
    assert "aria-label=" in indicator_body
    assert "sceneValidation.expected_folder_name" in indicator_body


def test_manager_frontend_scene_validation_pills_use_green_and_red_tokens() -> None:
    styles_source = read_source("styles.css")
    base_rule = get_css_rule(styles_source, ".scene-validation-pill")
    valid_rule = get_css_rule(styles_source, ".scene-validation-pill-valid")
    missing_rule = get_css_rule(styles_source, ".scene-validation-pill-missing")

    assert "--scene-valid:" in styles_source
    assert "--scene-valid-bg:" in styles_source
    assert "--scene-missing:" in styles_source
    assert "--scene-missing-bg:" in styles_source
    assert "display: inline-flex" in base_rule
    assert "flex: 0 0 auto" in base_rule
    assert "border-radius: var(--radius-pill)" in base_rule
    assert "background: var(--scene-valid-bg)" in valid_rule
    assert "color: var(--scene-valid)" in valid_rule
    assert "background: var(--scene-missing-bg)" in missing_rule


def test_manager_frontend_uses_fast_manifest_cache_without_scene_validation() -> None:
    api_source = read_source("api.ts")
    app_source = read_source("App.tsx")
    search_cache_body = app_source.split("async function cacheSearchManifests", 1)[1].split("void cacheSearchManifests", 1)[0]
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function loadSelectedManifestSceneValidation", 1)[0]
    select_body = app_source.split("async function handleSelect", 1)[1].split("function handleDateSelectFromList", 1)[0]

    assert "includeSceneValidation?: boolean" in api_source
    assert "scene_validation" in api_source
    assert "includeSceneValidation: false" in search_cache_body
    assert "refreshedSelected = await getShipment(currentSelectedId)" in refresh_body
    assert "refreshedSelected = await getShipment(currentSelected.id, { includeSceneValidation: false })" not in refresh_body
    assert "mergeFastRefreshManifest" not in app_source
    assert "await getShipment(summary.id, { includeSceneValidation: false })" in select_body
    assert "void loadSelectedManifestSceneValidation(manifest.id)" in select_body
    assert "async function loadSelectedManifestSceneValidation" in app_source


def test_manager_frontend_refresh_keeps_selected_summary_id_stable() -> None:
    app_source = read_source("App.tsx")
    refresh_body = app_source.split("async function refresh()", 1)[1].split("async function loadSelectedManifestSceneValidation", 1)[0]

    assert "const currentSelectedId = selectedSummaryIdRef.current" in refresh_body
    assert "if (currentSelectedId !== '')" in refresh_body
    assert "shipmentExists(nextTree, currentSelectedId)" in refresh_body
    assert "refreshedSelected = await getShipment(currentSelectedId)" in refresh_body
    assert "if (currentSelectedId !== '' && selectedSummaryIdRef.current !== currentSelectedId)" in refresh_body


def test_manager_frontend_prefetches_only_date_folder_navigation_titles_without_scene_validation() -> None:
    app_source = read_source("App.tsx")
    title_source = read_source("shipmentTitles.ts")
    navigation_cache_body = app_source.split("async function cacheNavigationTitleManifests", 1)[1].split("void cacheNavigationTitleManifests", 1)[0]

    assert "shouldLoadManifestForNavigation" in app_source
    assert "const uncachedNavigationTitleIds = useMemo" in app_source
    assert "shouldLoadManifestForNavigation(summary) && manifestCache[summary.id] === undefined" in app_source
    assert "await getShipment(id, { includeSceneValidation: false })" in navigation_cache_body
    assert "return isDateFolderName(summary.label)" in title_source
    assert "getDisplayFolderName(summary.label) === '밥스버거'" not in title_source


def test_manager_frontend_keeps_informative_bobs_summary_before_manifest_cache() -> None:
    title_source = read_source("shipmentTitles.ts")
    fallback_body = title_source.split("function getShipmentNavigationFallbackTitle", 1)[1].split("export function getShipmentNavigationTitle", 1)[0]

    assert "displayTitle === '밥스버거'" in fallback_body
    assert "summary.label.trim()" in fallback_body
    assert "return normalizedLabel" in fallback_body


def test_manager_frontend_bobs_titles_preserve_batch_tk_job_and_counts() -> None:
    title_source = read_source("shipmentTitles.ts")
    bobs_title_body = title_source.split("function getBobsManifestDisplayTitle", 1)[1].split("export function getManifestDisplayTitle", 1)[0]
    fallback_body = title_source.split("function getShipmentNavigationFallbackTitle", 1)[1].split("export function getShipmentNavigationTitle", 1)[0]

    assert "function getBobsBatchLabel" in title_source
    assert "batch${batchMatch[1]}" in title_source
    assert "const labelLabel = getBobsLabelLabel(sources)" in bobs_title_body
    assert "return buildBobsDisplayTitle(normalizedTitle, jobLabel, labelLabel, countLabel)" in bobs_title_body
    assert "return ['밥스버거', jobLabel, labelLabel, countLabel].filter(Boolean).join(' ')" in bobs_title_body
    assert "getBobsSummaryDisplayTitle(summary)" in fallback_body
    assert "summary.file_count > 0 ? `${summary.file_count}개 파일` : ''" in title_source
