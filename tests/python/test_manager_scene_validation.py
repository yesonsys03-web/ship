from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ship_common.models import FileEntry, ShipmentManifest
from ship_manager import service
from ship_manager import scene_validation


class FakeStorage:
    def __init__(self, manifest: Dict[str, Any]) -> None:
        self.manifest = manifest

    def load(self, shipment_id: str) -> Dict[str, Any]:
        assert shipment_id == self.manifest["id"]
        return self.manifest


def test_get_shipment_enriches_bobs_tk_scene_from_retake_shipping_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "BB"
        / "BB_062526_FASA13_TK1"
        / "13_TK1_062526"
        / "13_TK1_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-match",
        source_path="bobs://Bobs_Burgers/FASA13/batch/TK1/08A_S01",
        folder_name="밥스버거 FASA13 TK1 1개 씬",
        created_at="2026-06-25T01:02:03+00:00",
        files=[
            FileEntry(path="FASA13/TK1/08A_S01.bobs-scene", size=0, is_dir=False),
            FileEntry(path="notes.txt", size=12, is_dir=False),
        ],
    ).to_dict()
    fake_storage = FakeStorage(manifest)

    monkeypatch.setattr(service, "storage", fake_storage)
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-match")

    validation = result["files"][0]["scene_validation"]
    assert validation == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "scene-08A_S01",
        "matched_path": str(scene_folder),
        "reason": "matched_expected_folder",
    }
    assert "scene_validation" not in result["files"][1]
    assert "scene_validation" not in manifest["files"][0]


def test_get_shipment_enriches_bobs_batch_scene_from_batch_shipping_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_062526_FASA13_batch2"
        / "13_batch2_062526"
        / "13_batch2_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-batch-match",
        source_path="bobs://Bobs_Burgers/FASA13/batch/batch2/08A_S01",
        folder_name="밥스버거 FASA13 batch2 1개 씬",
        created_at="2026-06-25T01:02:03+00:00",
        files=[FileEntry(path="FASA13/08A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-batch-match")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "scene-08A_S01",
        "matched_path": str(scene_folder),
        "reason": "matched_expected_folder",
    }


def test_get_shipment_prefers_bobs_explicit_batch_folder_over_retake(monkeypatch, tmp_path: Path) -> None:
    batch_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_062526_FASA13_batch2"
        / "13_batch2_062526"
        / "13_batch2_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    retake_scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "BB"
        / "BB_062526_FASA13_batch2"
        / "13_batch2_062526"
        / "13_batch2_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    batch_scene_folder.mkdir(parents=True)
    retake_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-batch-preferred",
        source_path="bobs://Bobs_Burgers/FASA13/batch/batch2/08A_S01",
        folder_name="밥스버거 FASA13 batch2 1개 씬",
        created_at="2026-06-25T01:02:03+00:00",
        files=[FileEntry(path="FASA13/08A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-batch-preferred")

    assert result["files"][0]["scene_validation"]["matched_path"] == str(batch_scene_folder)


def test_get_shipment_matches_bobs_tk_scene_from_retake_take_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "BB"
        / "BB_070826_FASA12_take2"
        / "FASA12_take2"
        / "FASA12_take2_Harmony_070826"
        / "jobs"
        / "FASA12"
        / "scene-09_S02"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-bobs-tk2-take-match",
        source_path="bobs://Bobs_Burgers/FASA12/batch/TK2/09_S02+12_S06",
        folder_name="밥스버거 FASA12 TK2 2개 씬",
        created_at="2026-07-08T01:02:03+00:00",
        files=[FileEntry(path="FASA12/TK2/09_S02.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-bobs-tk2-take-match")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "scene-09_S02",
        "matched_path": str(scene_folder),
        "reason": "matched_expected_folder",
    }


def test_get_shipment_matches_bobs_retake_tk_scene_when_due_date_differs_from_take_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "BB"
        / "BB_070826_FASA12_take2"
        / "FASA12_take2"
        / "FASA12_take2_Harmony_070826"
        / "jobs"
        / "FASA12"
        / "scene-09_S02"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-bobs-retake-tk02-due-date-mismatch",
        source_path="bobs://Bobs_Burgers/FASA12/retake/TK02/09_S02+12_S06",
        folder_name="밥스버거 FASA12 TK02 2개 씬",
        created_at="2026-08-07T00:19:58.036Z",
        files=[FileEntry(path="FASA12/TK02/09_S02.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-bobs-retake-tk02-due-date-mismatch")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "scene-09_S02",
        "matched_path": str(scene_folder),
        "reason": "matched_expected_folder",
    }


def test_get_shipment_enriches_bobs_explicit_retake_tk1_scene(monkeypatch, tmp_path: Path) -> None:
    batch_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_062526_FASA13_TK1"
        / "13_TK1_062526"
        / "13_TK1_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    retake_scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "BB"
        / "BB_062526_FASA13_TK1"
        / "13_TK1_062526"
        / "13_TK1_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    batch_scene_folder.mkdir(parents=True)
    retake_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-retake-tk1",
        source_path="bobs://Bobs_Burgers/FASA13/retake/TK1/08A_S01",
        folder_name="밥스버거 FASA13 TK1 1개 씬",
        created_at="2026-06-25T01:02:03+00:00",
        files=[FileEntry(path="FASA13/TK1/08A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-retake-tk1")

    assert result["files"][0]["scene_validation"]["matched_path"] == str(retake_scene_folder)


def test_get_shipment_ignores_bobs_scene_folder_outside_job_token_folder(monkeypatch, tmp_path: Path) -> None:
    old_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_062526_FASA13_batch2"
        / "13_batch2_062526"
        / "13_batch2_Harmony_062526"
        / "jobs"
        / "FASA13"
        / "scene-08B_S12"
    )
    current_sibling_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_071426_FASA13_batch2"
        / "13_batch2_071426"
        / "13_batch2_Harmony_071426"
        / "jobs"
        / "scene-08B_S12"
    )
    old_scene_folder.mkdir(parents=True)
    current_sibling_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-bobs-current-date",
        source_path="bobs://Bobs_Burgers/FASA13/batch/batch2/08B_S12",
        folder_name="밥스버거 FASA13 batch2 1개 씬",
        created_at="2026-07-14T02:45:33.766Z",
        sent_at="2026-07-14T02:45:33.784406+00:00",
        files=[FileEntry(path="FASA13/08B_S12.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-bobs-current-date")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "scene-08B_S12",
        "matched_path": None,
        "reason": "expected_folder_not_found",
    }


def test_get_shipment_prioritizes_current_bobs_root_before_broad_walk_limit(monkeypatch, tmp_path: Path) -> None:
    old_root = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_062526_FASA13_batch2"
        / "13_batch2_062526"
        / "13_batch2_Harmony_062526"
        / "jobs"
        / "FASA13"
    )
    current_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_071426_FASA13_batch2"
        / "13_batch2_071426"
        / "13_batch2_Harmony_071426"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    old_root.mkdir(parents=True)
    current_scene_folder.mkdir(parents=True)
    for index in range(10):
        (old_root / f"noise-{index:02d}").mkdir()
    manifest = ShipmentManifest(
        id="ship-scene-bobs-current-before-cap",
        source_path="bobs://Bobs_Burgers/FASA13/batch/batch2/08A_S01",
        folder_name="밥스버거 FASA13 batch2 1개 씬",
        created_at="2026-07-14T02:45:33.766Z",
        files=[FileEntry(path="FASA13/08A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")
    monkeypatch.setattr(scene_validation, "MAX_VISITED_DIRECTORIES_PER_ROOT", 6)

    result = service.get_shipment("/api/shipment?id=ship-scene-bobs-current-before-cap")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "scene-08A_S01",
        "matched_path": str(current_scene_folder),
        "reason": "matched_expected_folder",
    }


def test_get_shipment_marks_bobs_scene_missing_when_bounded_roots_do_not_exist(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-scene-missing",
        source_path="bobs://Bobs_Burgers/FASA13/batch/01A_S01",
        folder_name="밥스버거 FASA13 1개 씬",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="01A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "missing-shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-missing")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "scene-01A_S01",
        "matched_path": None,
        "reason": "bounded_roots_missing",
    }


def test_get_shipment_marks_bobs_scene_missing_when_same_scene_exists_in_other_batch(monkeypatch, tmp_path: Path) -> None:
    wrong_batch_scene = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_071426_FASA13_batch1"
        / "13_batch1_071426"
        / "13_batch1_Harmony_071426"
        / "jobs"
        / "FASA13"
        / "scene-08B_S12"
    )
    wrong_batch_scene.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-other-batch",
        source_path="bobs://Bobs_Burgers/FASA13/batch/batch2/08B_S12",
        folder_name="밥스버거 FASA13 batch2 1개 씬",
        created_at="2026-07-01T01:02:03+00:00",
        files=[FileEntry(path="FASA13/08B_S12.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-other-batch")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "scene-08B_S12",
        "matched_path": None,
        "reason": "expected_folder_not_found",
    }


def test_get_shipment_enriches_hazbin_scene_from_hh_batch_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "HH"
        / "HH_071426_HH304_batch2"
        / "04_batch2_071426"
        / "04_batch2_Harmony_071426"
        / "HH_304"
        / "HH0304_020_0300_OSRO_v02"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-hh-scene-match",
        source_path="/System/Volumes/Data/shipping/Shipping/Hazbin_Hotel/2026_07/2026_0714",
        folder_name="2026_0714",
        created_at="2026-07-15T01:02:03+00:00",
        files=[FileEntry(path="HH_304/OSRO_mov/HH0304_020_0300_OSRO_v02.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-hh-scene-match")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "HH0304_020_0300_OSRO_v02",
        "matched_path": str(scene_folder),
        "reason": "matched_expected_folder",
    }


def test_hazbin_job_token_requires_valid_hh_scene_folder_part() -> None:
    assert scene_validation._has_job_token_path_part(Path("/shipping/HH0304_020_0300_OSRO_v02"), ["HH0304"])
    assert scene_validation._has_job_token_path_part(Path("/shipping/HH0304_020_0300_OSRO"), ["HH0304"])
    assert not scene_validation._has_job_token_path_part(Path("/shipping/HH0304_backup"), ["HH0304"])
    assert not scene_validation._has_job_token_path_part(Path("/shipping/HH0304_020_0300_OSRO_v02.mov"), ["HH0304"])


def test_get_shipment_requires_exact_hazbin_versioned_scene_folder(monkeypatch, tmp_path: Path) -> None:
    versionless_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "HH"
        / "HH_071426_HH304_batch1"
        / "04_batch1_071426"
        / "04_batch1_Harmony_071426"
        / "HH_304"
        / "HH0304_999_9999_OSRO"
    )
    versionless_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-hh-versioned-folder-missing",
        source_path="/System/Volumes/Data/shipping/Shipping/Hazbin_Hotel/2026_07/2026_0714",
        folder_name="2026_0714",
        created_at="2026-07-15T01:02:03+00:00",
        files=[FileEntry(path="HH_304/OSRO_mov/HH0304_999_9999_OSRO_v01.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-hh-versioned-folder-missing")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "HH0304_999_9999_OSRO_v01",
        "matched_path": None,
        "reason": "expected_folder_not_found",
    }


def test_get_shipment_rejects_hazbin_scene_folder_outside_episode_folder(monkeypatch, tmp_path: Path) -> None:
    sibling_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "HH"
        / "HH_071426_HH304_batch1"
        / "04_batch1_071426"
        / "04_batch1_Harmony_071426"
        / "HH0304_080_0250_OSRO_v01"
    )
    sibling_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-hh-scene-sibling-folder",
        source_path="/System/Volumes/Data/shipping/Shipping/Hazbin_Hotel/2026_07/2026_0714",
        folder_name="2026_0714",
        created_at="2026-07-15T01:02:03+00:00",
        files=[FileEntry(path="HH_304/OSRO_mov/HH0304_080_0250_OSRO_v01.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-hh-scene-sibling-folder")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "HH0304_080_0250_OSRO_v01",
        "matched_path": None,
        "reason": "expected_folder_not_found",
    }


def test_get_shipment_enriches_multi_episode_hazbin_manifest_with_per_file_context(monkeypatch, tmp_path: Path) -> None:
    scene_folders = [
        (
            tmp_path
            / "shipping"
            / "batch"
            / "HH"
            / "HH_071426_HH304_batch1"
            / "04_batch1_071426"
            / "04_batch1_Harmony_071426"
            / "HH_304"
            / "HH0304_020_0300_OSRO_v02"
        ),
        (
            tmp_path
            / "shipping"
            / "batch"
            / "HH"
            / "HH_071426_HH305_batch1"
            / "05_batch1_071426"
            / "05_batch1_Harmony_071426"
            / "HH_305"
            / "HH0305_010_0200_OSCY_v01"
        ),
        (
            tmp_path
            / "shipping"
            / "batch"
            / "HH"
            / "HH_071426_HH306_batch1"
            / "06_batch1_071426"
            / "06_batch1_Harmony_071426"
            / "HH_306"
            / "HH0306_020_0140_OSCY_v01"
        ),
    ]
    for scene_folder in scene_folders:
        scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-hh-multi-episode-scene-match",
        source_path="/System/Volumes/Data/shipping/Shipping/Hazbin_Hotel/2026_07/2026_0714",
        folder_name="2026_0714",
        created_at="2026-07-15T04:46:04+00:00",
        files=[
            FileEntry(path="HH_304/OSRO_mov/HH0304_020_0300_OSRO_v02.mov", size=12, is_dir=False),
            FileEntry(path="HH_305/OSCY_mov/HH0305_010_0200_OSCY_v01.mov", size=12, is_dir=False),
            FileEntry(path="HH_306/OSCY_mov/HH0306_020_0140_OSCY_v01.mov", size=12, is_dir=False),
        ],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-hh-multi-episode-scene-match")

    validations = [file["scene_validation"] for file in result["files"]]
    assert [validation["exists"] for validation in validations] == [True, True, True]
    assert [validation["matched_path"] for validation in validations] == [str(scene_folder) for scene_folder in scene_folders]


def test_get_shipment_enriches_koth_scene_from_koth_batch_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "KOTH"
        / "Yeson_1510_071426_TK1"
        / "KOTH_1510_071426"
        / "KOTH_1510_Harmony_TK1"
        / "1510"
        / "scene-1510_T001"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-koth-scene-match",
        source_path="/tmp/KOTH/1510_TK1_delivery",
        folder_name="킹오브더힐 1510",
        created_at="2026-07-14T01:02:03+00:00",
        files=[FileEntry(path="1510_T001.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-koth-scene-match")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert result["files"][0]["scene_validation"]["matched_path"] == str(scene_folder)


def test_get_shipment_enriches_koth_promo_scene_from_matching_child_root(monkeypatch, tmp_path: Path) -> None:
    old_root = tmp_path / "shipping" / "batch" / "KOTH" / "Yeson_1510_071426_TK1" / "noise"
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "KOTH"
        / "1510_PROMO-TK1_0713_2026"
        / "KOTH_1510_PROMO_071326"
        / "KOTH_1510_PROMO_Harmony_TK1"
        / "1510_PROMO"
        / "923"
    )
    old_root.mkdir(parents=True)
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-koth-promo-scene-match",
        source_path="/tmp/KOTH/1510_PROMO-TK1_0713_2026",
        folder_name="1510_PROMO-TK1_0713_2026",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="킹오브더힐/1510_PROMO_923_v001.mov", size=12, is_dir=False)],
    ).to_dict()
    original_walk_bounded = scene_validation._walk_bounded
    walked_roots: list[Path] = []

    def tracking_walk(root_path: Path):
        walked_roots.append(root_path)
        yield from original_walk_bounded(root_path)

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")
    monkeypatch.setattr(scene_validation, "_walk_bounded", tracking_walk)

    result = service.get_shipment("/api/shipment?id=ship-koth-promo-scene-match")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert result["files"][0]["scene_validation"]["matched_path"] == str(scene_folder)
    assert walked_roots == []


def test_get_shipment_marks_missing_koth_promo_numeric_shot_folder(monkeypatch, tmp_path: Path) -> None:
    existing_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "KOTH"
        / "1510_PROMO-TK1_0713_2026"
        / "KOTH_1510_PROMO_071326"
        / "KOTH_1510_PROMO_Harmony_TK1"
        / "sc923thru933_BestFriends"
        / "933"
    )
    existing_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-koth-promo-missing-934",
        source_path="/tmp/KOTH/1510_PROMO-TK1_0713_2026",
        folder_name="1510_PROMO-TK1_0713_2026",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="킹오브더힐/1510_PROMO_934_v001.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-koth-promo-missing-934")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "scene-1510_PROMO_934",
        "matched_path": None,
        "reason": "expected_folder_not_found",
    }


def test_get_shipment_ignores_koth_numeric_shot_folder_in_decoy_branch(monkeypatch, tmp_path: Path) -> None:
    decoy_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "KOTH"
        / "1510_PROMO-TK1_0713_2026"
        / "KOTH_1510_PROMO_071326"
        / "KOTH_1510_PROMO_Harmony_TK1"
        / "000_archive"
        / "934"
    )
    decoy_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-koth-promo-decoy-934",
        source_path="/tmp/KOTH/1510_PROMO-TK1_0713_2026",
        folder_name="1510_PROMO-TK1_0713_2026",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="킹오브더힐/1510_PROMO_934_v001.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-koth-promo-decoy-934")

    assert result["files"][0]["scene_validation"]["exists"] is False
    assert result["files"][0]["scene_validation"]["matched_path"] is None


def test_get_shipment_accepts_koth_numeric_shot_folder_under_harmony(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "KOTH"
        / "1510_PROMO-TK1_0713_2026"
        / "KOTH_1510_PROMO_071326"
        / "KOTH_1510_PROMO_Harmony_TK1"
        / "934"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-koth-promo-harmony-934",
        source_path="/tmp/KOTH/1510_PROMO-TK1_0713_2026",
        folder_name="1510_PROMO-TK1_0713_2026",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="킹오브더힐/1510_PROMO_934_v001.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-koth-promo-harmony-934")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert result["files"][0]["scene_validation"]["matched_path"] == str(scene_folder)


def test_get_shipment_accepts_koth_numeric_shot_folder_in_range_parent(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "KOTH"
        / "1510_PROMO-TK1_0713_2026"
        / "KOTH_1510_PROMO_071326"
        / "KOTH_1510_PROMO_Harmony_TK1"
        / "sc923thru933_BestFriends"
        / "923"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-koth-promo-range-923",
        source_path="/tmp/KOTH/1510_PROMO-TK1_0713_2026",
        folder_name="1510_PROMO-TK1_0713_2026",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="킹오브더힐/1510_PROMO_923_v001.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-koth-promo-range-923")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert result["files"][0]["scene_validation"]["matched_path"] == str(scene_folder)


def test_get_shipment_enriches_florida_tk1_scene_from_batch_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "FL"
        / "FL_102_TK1_071426"
        / "FL_102_071426"
        / "FL_102_Harmony_TK1"
        / "FL_102"
        / "T008"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-fl-scene-match",
        source_path="/tmp/FL_102_TK1_delivery",
        folder_name="플로리다 102화",
        created_at="2026-07-14T01:02:03+00:00",
        files=[FileEntry(path="FL_102_T008_TK1.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-fl-scene-match")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": True,
        "expected_folder_name": "scene-FL_102_T008",
        "matched_path": str(scene_folder),
        "reason": "matched_expected_folder",
    }


def test_get_shipment_enriches_florida_tk3_scene_from_retake_folder(monkeypatch, tmp_path: Path) -> None:
    batch_scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "FL"
        / "FL_102_TK3_071426"
        / "FL_102_071426"
        / "FL_102_Harmony_TK3"
        / "FL_102"
        / "T008"
    )
    retake_scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "FL"
        / "FL_102_TK3_071426"
        / "FL_102_071426"
        / "FL_102_Harmony_TK3"
        / "FL_102"
        / "T008"
    )
    batch_scene_folder.mkdir(parents=True)
    retake_scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-fl-tk3-scene-match",
        source_path="/tmp/FL_102_TK3_delivery",
        folder_name="플로리다 102화",
        created_at="2026-07-14T01:02:03+00:00",
        files=[FileEntry(path="FL_102_T008_TK3.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-fl-tk3-scene-match")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert result["files"][0]["scene_validation"]["matched_path"] == str(retake_scene_folder)


def test_get_shipment_enriches_florida_tk3_scene_when_root_is_date_folder(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "FL"
        / "FL_102_TK3_071426"
        / "FL_102_071426"
        / "FL_102_Harmony_TK3"
        / "FL_102"
        / "T008"
    )
    scene_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-fl-tk3-date-folder-match",
        source_path="/Volumes/data/tttest/2026_0714",
        folder_name="2026_0714",
        created_at="2026-07-15T01:59:09+00:00",
        files=[FileEntry(path="FL_102-TK3_0714_2026/FL_102_T008_TK3.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-fl-tk3-date-folder-match")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert result["files"][0]["scene_validation"]["matched_path"] == str(scene_folder)


def test_get_shipment_rejects_florida_task_folder_outside_episode_folder(monkeypatch, tmp_path: Path) -> None:
    decoy_task_folder = (
        tmp_path
        / "shipping"
        / "retake"
        / "FL"
        / "FL_102_TK3_071426"
        / "FL_102_071426"
        / "FL_102_Harmony_TK3"
        / "T008"
    )
    decoy_task_folder.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-fl-tk3-decoy-task-folder",
        source_path="/tmp/FL_102_TK3_delivery",
        folder_name="플로리다 102화",
        created_at="2026-07-14T01:02:03+00:00",
        files=[FileEntry(path="FL_102_T008_TK3.mov", size=12, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "shipping")

    result = service.get_shipment("/api/shipment?id=ship-fl-tk3-decoy-task-folder")

    assert result["files"][0]["scene_validation"] == {
        "checked": True,
        "exists": False,
        "expected_folder_name": "scene-FL_102_T008",
        "matched_path": None,
        "reason": "expected_folder_not_found",
    }


def test_get_shipment_can_skip_scene_validation_for_title_cache(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-scene-cache-title",
        source_path="bobs://Bobs_Burgers/FASA13/batch/01A_S01",
        folder_name="밥스버거 FASA13 1개 씬",
        created_at="2026-07-13T01:02:03+00:00",
        files=[FileEntry(path="01A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()

    monkeypatch.setattr(service, "storage", FakeStorage(manifest))
    monkeypatch.setattr(service, "SHIP_SCENE_ROOT", tmp_path / "missing-shipping")

    result = service.get_shipment("/api/shipment?id=ship-scene-cache-title&scene_validation=0")

    assert result == manifest
    assert "scene_validation" not in result["files"][0]


def test_enrich_manifest_scene_validation_uses_shallow_lookup_before_broad_walk(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "shipping" / "batch" / "BB" / "BB_071326_FASA13_batch2" / "13_batch2_071326"
    scene_one = root / "jobs" / "FASA13" / "scene-01A_S01"
    scene_two = root / "jobs" / "FASA13" / "scene-01A_S02"
    scene_one.mkdir(parents=True)
    scene_two.mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-batch-walk",
        source_path="bobs://Bobs_Burgers/FASA13/batch/01A_S01+01A_S02",
        folder_name="밥스버거 FASA13 2개 씬",
        created_at="2026-07-13T01:02:03+00:00",
        files=[
            FileEntry(path="01A_S01.bobs-scene", size=0, is_dir=False),
            FileEntry(path="01A_S02.bobs-scene", size=0, is_dir=False),
        ],
    ).to_dict()
    original_walk_bounded = scene_validation._walk_bounded
    walked_roots: list[Path] = []

    def tracking_walk(root_path: Path):
        walked_roots.append(root_path)
        yield from original_walk_bounded(root_path)

    monkeypatch.setattr(scene_validation, "_walk_bounded", tracking_walk)

    result = scene_validation.enrich_manifest_scene_validation(manifest, tmp_path / "shipping")

    assert [file["scene_validation"]["exists"] for file in result["files"]] == [True, True]
    assert walked_roots == []


def test_enrich_manifest_scene_validation_does_not_walk_inside_scene_folders(monkeypatch, tmp_path: Path) -> None:
    scene_folder = (
        tmp_path
        / "shipping"
        / "batch"
        / "BB"
        / "BB_071426_FASA13_batch2"
        / "13_batch2_071426"
        / "13_batch2_Harmony_071426"
        / "jobs"
        / "FASA13"
        / "scene-08A_S01"
    )
    (scene_folder / "elements" / "heavy" / "nested").mkdir(parents=True)
    manifest = ShipmentManifest(
        id="ship-scene-prune",
        source_path="bobs://Bobs_Burgers/FASA13/batch/batch2/08A_S01",
        folder_name="밥스버거 FASA13 batch2 1개 씬",
        created_at="2026-07-14T02:45:33.766Z",
        files=[FileEntry(path="FASA13/08A_S01.bobs-scene", size=0, is_dir=False)],
    ).to_dict()
    original_walk_bounded = scene_validation._walk_bounded
    walked_dirs: list[Path] = []

    def tracking_walk(root_path: Path):
        for current_dir, child_names in original_walk_bounded(root_path):
            walked_dirs.append(current_dir)
            yield current_dir, child_names

    monkeypatch.setattr(scene_validation, "_walk_bounded", tracking_walk)

    result = scene_validation.enrich_manifest_scene_validation(manifest, tmp_path / "shipping")

    assert result["files"][0]["scene_validation"]["exists"] is True
    assert scene_folder not in walked_dirs
    assert scene_folder / "elements" not in walked_dirs
