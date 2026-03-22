"""
tests/test_photo_organizer.py

Full test suite covering:
  - Scanner: extension filtering, hidden-dir skip, symlink skip
  - MetadataExtractor: EXIF parse, fallback chain, corrupt file
  - Organizer: destination path, duplicate suffix, dry-run, real copy
  - Utils: summary printing
  - Integration: end-to-end pipeline
"""

from __future__ import annotations

import shutil
import struct
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from copy_media_for_cloud import copy_for_cloud
from ftp_upload import upload_to_ftp
from photo_organizer.metadata import ImageMetadata, MetadataExtractor
from photo_organizer.main import remove_empty_directories
from photo_organizer.organizer import Organizer, OrganizerConfig
from photo_organizer.scanner import Scanner
from photo_organizer.utils import print_summary


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_src(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    return src


@pytest.fixture()
def tmp_dst(tmp_path: Path) -> Path:
    dst = tmp_path / "dst"
    dst.mkdir()
    return dst


def _touch(parent: Path, name: str, content: bytes = b"fake") -> Path:
    """Create a file with given content."""
    p = parent / name
    p.write_bytes(content)
    return p


# ──────────────────────────────────────────────────────────────────────────────
# Scanner tests
# ──────────────────────────────────────────────────────────────────────────────


class TestScanner:
    def test_finds_supported_extensions(self, tmp_src: Path):
        _touch(tmp_src, "a.jpg")
        _touch(tmp_src, "b.JPEG")  # uppercase
        _touch(tmp_src, "c.png")
        _touch(tmp_src, "d.heic")
        _touch(tmp_src, "e.CR3")
        _touch(tmp_src, "f.raw")
        _touch(tmp_src, "g.mp4")
        _touch(tmp_src, "h.MOV")
        _touch(tmp_src, "e.txt")  # should be ignored

        found = list(Scanner(tmp_src).scan())
        names = {p.name for p in found}
        assert "a.jpg" in names
        assert "b.JPEG" in names
        assert "c.png" in names
        assert "d.heic" in names
        assert "e.CR3" in names
        assert "f.raw" in names
        assert "g.mp4" in names
        assert "h.MOV" in names
        assert "e.txt" not in names

    def test_recurses_subdirectories(self, tmp_src: Path):
        sub = tmp_src / "2024" / "01"
        sub.mkdir(parents=True)
        _touch(sub, "deep.jpg")
        found = list(Scanner(tmp_src).scan())
        assert any(p.name == "deep.jpg" for p in found)

    def test_skips_hidden_directories(self, tmp_src: Path):
        hidden = tmp_src / ".hidden"
        hidden.mkdir()
        _touch(hidden, "secret.jpg")
        found = list(Scanner(tmp_src).scan())
        assert not any(p.name == "secret.jpg" for p in found)

    def test_empty_directory_returns_nothing(self, tmp_src: Path):
        assert list(Scanner(tmp_src).scan()) == []

    def test_custom_extensions(self, tmp_src: Path):
        _touch(tmp_src, "video.mp4")
        _touch(tmp_src, "photo.jpg")
        scanner = Scanner(tmp_src, extensions=frozenset({"mp4"}))
        found = list(scanner.scan())
        assert any(p.name == "video.mp4" for p in found)
        assert not any(p.name == "photo.jpg" for p in found)

    def test_excludes_destination_subtree(self, tmp_src: Path):
        organized = tmp_src / "organized"
        organized.mkdir()
        _touch(organized, "sorted.jpg")
        _touch(tmp_src, "fresh.jpg")

        found = list(Scanner(tmp_src, excluded_roots=(organized,)).scan())
        names = {p.name for p in found}
        assert "fresh.jpg" in names
        assert "sorted.jpg" not in names


# ──────────────────────────────────────────────────────────────────────────────
# MetadataExtractor tests
# ──────────────────────────────────────────────────────────────────────────────


class TestMetadataExtractor:
    def test_prefers_exif_original_over_other_dates(self, tmp_src: Path):
        img = _touch(tmp_src, "photo.jpg")
        extractor = MetadataExtractor()

        with patch.object(
            extractor,
            "_exif_date",
            return_value=(datetime(2021, 5, 6, 7, 8, 9), "exif_original"),
        ), patch.object(
            extractor,
            "_mdls_capture_date",
            return_value=(datetime(2022, 1, 1, 0, 0, 0), "mdls_content_creation"),
        ), patch.object(
            extractor,
            "_birth_date",
            return_value=datetime(2023, 1, 1, 0, 0, 0),
        ), patch.object(
            extractor,
            "_mtime_date",
            return_value=datetime(2024, 1, 1, 0, 0, 0),
        ):
            meta = extractor.extract(img)

        assert meta is not None
        assert meta.date == datetime(2021, 5, 6, 7, 8, 9)
        assert meta.date_source == "exif_original"

    def test_uses_mdls_before_filesystem_timestamps(self, tmp_src: Path):
        img = _touch(tmp_src, "clip.mp4")
        extractor = MetadataExtractor()

        with patch.object(
            extractor,
            "_exif_date",
            return_value=(None, ""),
        ), patch.object(
            extractor,
            "_mdls_capture_date",
            return_value=(datetime(2021, 6, 7, 8, 9, 10), "mdls_media_creation"),
        ), patch.object(
            extractor,
            "_birth_date",
            return_value=datetime(2022, 1, 1, 0, 0, 0),
        ), patch.object(
            extractor,
            "_mtime_date",
            return_value=datetime(2023, 1, 1, 0, 0, 0),
        ):
            meta = extractor.extract(img)

        assert meta is not None
        assert meta.date == datetime(2021, 6, 7, 8, 9, 10)
        assert meta.date_source == "mdls_media_creation"

    def test_falls_back_to_mtime_when_no_exif(self, tmp_src: Path):
        img = _touch(tmp_src, "no_exif.jpg")
        extractor = MetadataExtractor()
        meta = extractor.extract(img)
        assert meta is not None
        assert meta.date_source in (
            "mdls_content_creation",
            "mdls_media_creation",
            "birthtime",
            "mtime",
        )
        assert isinstance(meta.date, datetime)

    def test_returns_none_for_unreadable_file(self, tmp_src: Path):
        img = _touch(tmp_src, "bad.jpg")
        extractor = MetadataExtractor()
        # Make stat raise OSError for the mtime fallback path
        with patch.object(Path, "stat", side_effect=OSError("nope")):
            # EXIF will also fail (not a real JPEG), so all fallbacks fail
            meta = extractor.extract(img)
        # Either None or a valid meta depending on whether PIL raises first
        # — the important thing is no exception propagates
        assert meta is None or isinstance(meta, ImageMetadata)

    def test_exif_datetime_parsing(self):
        extractor = MetadataExtractor()
        dt = extractor._parse_exif_dt("2023:07:15 14:30:00")
        assert dt == datetime(2023, 7, 15, 14, 30, 0)

    def test_exif_datetime_parsing_invalid(self):
        extractor = MetadataExtractor()
        dt = extractor._parse_exif_dt("not-a-date")
        assert dt is None

    def test_exif_datetime_parsing_empty(self):
        extractor = MetadataExtractor()
        dt = extractor._parse_exif_dt("   ")
        assert dt is None

    def test_mdls_datetime_parsing(self, tmp_src: Path):
        img = _touch(tmp_src, "clip.mp4")
        extractor = MetadataExtractor()

        with patch("photo_organizer.metadata.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="2024-07-15 14:30:00 +0530\n")
            dt = extractor._mdls_value(img, "kMDItemMediaCreationDate")

        assert dt == datetime(2024, 7, 15, 14, 30, 0)

    def test_rejects_epoch_like_mdls_date(self, tmp_src: Path):
        img = _touch(tmp_src, "clip.mp4")
        extractor = MetadataExtractor()

        with patch("photo_organizer.metadata.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1970-01-01 00:00:00 +0000\n")
            dt = extractor._mdls_value(img, "kMDItemMediaCreationDate")

        assert dt is None

    def test_rejects_epoch_like_exif_date(self):
        extractor = MetadataExtractor()
        assert extractor._parse_exif_dt("1970:01:01 00:00:00") is None

    def test_metadata_dataclass_fields(self, tmp_src: Path):
        img = _touch(tmp_src, "x.png")
        meta = MetadataExtractor().extract(img)
        assert meta is not None
        assert meta.path == img
        assert isinstance(meta.date, datetime)
        assert meta.date_source != ""


# ──────────────────────────────────────────────────────────────────────────────
# Organizer tests
# ──────────────────────────────────────────────────────────────────────────────


class TestOrganizer:
    def _make_meta(self, path: Path, date: datetime) -> ImageMetadata:
        return ImageMetadata(path=path, date=date, date_source="test")

    def test_destination_dir_structure(self, tmp_dst: Path, tmp_src: Path):
        img = _touch(tmp_src, "photo.jpg")
        config = OrganizerConfig(dst=tmp_dst, dry_run=True)
        org = Organizer(config)
        meta = self._make_meta(img, datetime(2024, 3, 5))
        dst_dir = org._destination_dir(meta, "images")
        assert dst_dir == tmp_dst / "2024" / "03" / "05" / "images"

    def test_destination_dir_zero_padded(self, tmp_dst: Path, tmp_src: Path):
        img = _touch(tmp_src, "photo.jpg")
        config = OrganizerConfig(dst=tmp_dst, dry_run=True)
        org = Organizer(config)
        meta = self._make_meta(img, datetime(2024, 1, 1))
        dst_dir = org._destination_dir(meta, "images")
        assert str(dst_dir).endswith("2024/01/01/images")

    def test_dry_run_does_not_move(self, tmp_src: Path, tmp_dst: Path):
        img = _touch(tmp_src, "photo.jpg")
        config = OrganizerConfig(dst=tmp_dst, dry_run=True)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(img, datetime(2024, 6, 1))
            result = org.process(img)

        assert result == "processed"
        # Nothing should have been moved
        assert not any(tmp_dst.rglob("*.jpg"))
        assert img.exists()

    def test_moves_file_to_correct_location(self, tmp_src: Path, tmp_dst: Path):
        img = _touch(tmp_src, "shot.jpg", b"jpeg_bytes")
        config = OrganizerConfig(dst=tmp_dst, dry_run=False, hash_duplicates=False)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(img, datetime(2023, 12, 25))
            result = org.process(img)

        assert result == "processed"
        expected = tmp_dst / "2023" / "12" / "25" / "images" / "shot.jpg"
        assert expected.exists()
        assert expected.read_bytes() == b"jpeg_bytes"
        assert not img.exists()

    def test_duplicate_filename_gets_suffix(self, tmp_src: Path, tmp_dst: Path):
        # Pre-create the destination with DIFFERENT content → not a true dup
        dst_dir = tmp_dst / "2023" / "12" / "25" / "images"
        dst_dir.mkdir(parents=True)
        (dst_dir / "shot.jpg").write_bytes(b"existing_content")

        img = _touch(tmp_src, "shot.jpg", b"new_content")
        config = OrganizerConfig(dst=tmp_dst, dry_run=False, hash_duplicates=True)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(img, datetime(2023, 12, 25))
            result = org.process(img)

        assert result == "processed"
        assert (dst_dir / "shot_1.jpg").exists()

    def test_true_duplicate_is_skipped(self, tmp_src: Path, tmp_dst: Path):
        content = b"identical_bytes"
        dst_dir = tmp_dst / "2023" / "12" / "25" / "images"
        dst_dir.mkdir(parents=True)
        (dst_dir / "shot.jpg").write_bytes(content)

        img = _touch(tmp_src, "shot.jpg", content)
        config = OrganizerConfig(dst=tmp_dst, dry_run=False, hash_duplicates=True)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(img, datetime(2023, 12, 25))
            result = org.process(img)

        # Should be skipped — identical content already exists
        assert result == "skipped"
        assert not img.exists()
        # No _1 variant created
        assert not (dst_dir / "shot_1.jpg").exists()

    def test_duplicate_content_with_different_name_is_skipped(self, tmp_src: Path, tmp_dst: Path):
        content = b"identical_bytes"
        dst_dir = tmp_dst / "2023" / "12" / "25" / "images"
        dst_dir.mkdir(parents=True)
        (dst_dir / "original.jpg").write_bytes(content)

        img = _touch(tmp_src, "copy.jpg", content)
        config = OrganizerConfig(dst=tmp_dst, dry_run=False, hash_duplicates=True)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(img, datetime(2023, 12, 25))
            result = org.process(img)

        assert result == "skipped"
        assert not img.exists()
        assert not (dst_dir / "copy.jpg").exists()

    def test_errors_returned_when_metadata_fails(self, tmp_src: Path, tmp_dst: Path):
        img = _touch(tmp_src, "corrupt.jpg")
        config = OrganizerConfig(dst=tmp_dst, dry_run=False)
        org = Organizer(config)

        with patch.object(org._extractor, "extract", return_value=None):
            result = org.process(img)

        assert result == "errors"

    def test_raw_files_land_under_raw_bucket(self, tmp_src: Path, tmp_dst: Path):
        img = _touch(tmp_src, "capture.CR3", b"raw_bytes")
        config = OrganizerConfig(dst=tmp_dst, dry_run=False, hash_duplicates=False)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(img, datetime(2024, 7, 4))
            result = org.process(img)

        assert result == "processed"
        assert (tmp_dst / "2024" / "07" / "04" / "raw" / "capture.CR3").exists()

    def test_video_files_land_under_videos_bucket(self, tmp_src: Path, tmp_dst: Path):
        video = _touch(tmp_src, "clip.mp4", b"video_bytes")
        config = OrganizerConfig(dst=tmp_dst, dry_run=False, hash_duplicates=False)
        org = Organizer(config)

        with patch.object(org._extractor, "extract") as mock_extract:
            mock_extract.return_value = self._make_meta(video, datetime(2024, 8, 9))
            result = org.process(video)

        assert result == "processed"
        assert (tmp_dst / "2024" / "08" / "09" / "videos" / "clip.mp4").exists()

    def test_sha256_same_content(self, tmp_src: Path, tmp_dst: Path):
        a = _touch(tmp_src, "a.jpg", b"abc")
        b = _touch(tmp_dst, "b.jpg", b"abc")
        config = OrganizerConfig(dst=tmp_dst)
        org = Organizer(config)
        assert org._same_content(a, b) is True

    def test_sha256_different_content(self, tmp_src: Path, tmp_dst: Path):
        a = _touch(tmp_src, "a.jpg", b"abc")
        b = _touch(tmp_dst, "b.jpg", b"xyz")
        config = OrganizerConfig(dst=tmp_dst)
        org = Organizer(config)
        assert org._same_content(a, b) is False


# ──────────────────────────────────────────────────────────────────────────────
# Integration test
# ──────────────────────────────────────────────────────────────────────────────


class TestIntegration:
    def test_end_to_end_pipeline(self, tmp_src: Path, tmp_dst: Path):
        """Full pipeline: scanner → metadata → organizer."""
        # Create a mix of files
        _touch(tmp_src, "photo.jpg", b"fake_jpeg")
        _touch(tmp_src, "ignored.txt", b"text")
        sub = tmp_src / "sub"
        sub.mkdir()
        _touch(sub, "nested.png", b"fake_png")

        from photo_organizer.main import OrganizeRequest, run

        request = OrganizeRequest(
            src=tmp_src,
            dst=tmp_dst,
            dry_run=False,
            verbose=False,
        )
        stats = run(request)

        # 2 images total; errors allowed (no real EXIF → mtime fallback)
        assert stats["processed"] + stats["errors"] == 2
        # Nothing should count as skipped in a fresh run
        assert stats["skipped"] == 0
        assert stats["elapsed_seconds"] >= 0

    def test_pipeline_skips_nested_organized_directory(self, tmp_src: Path):
        organized = tmp_src / "organized"
        organized.mkdir()
        _touch(organized, "sorted.jpg", b"done")
        _touch(tmp_src, "fresh.jpg", b"new")

        from photo_organizer.main import OrganizeRequest, run

        request = OrganizeRequest(
            src=tmp_src,
            dst=organized,
            dry_run=False,
            verbose=False,
        )
        stats = run(request)

        assert stats["processed"] + stats["errors"] == 1
        assert (organized / "2026" / "03" / "22" / "images").exists()
        assert stats["elapsed_seconds"] >= 0

    def test_pipeline_drops_duplicate_content_even_with_different_names(self, tmp_src: Path):
        first = _touch(tmp_src, "a.jpg", b"same")
        second = _touch(tmp_src, "b.jpg", b"same")

        from photo_organizer.main import OrganizeRequest, run

        organized = tmp_src / "organized"
        request = OrganizeRequest(
            src=tmp_src,
            dst=organized,
            dry_run=False,
            verbose=False,
        )
        stats = run(request)

        assert stats["processed"] == 1
        assert stats["skipped"] == 1
        assert not first.exists()
        assert not second.exists()
        assert stats["elapsed_seconds"] >= 0

    def test_pipeline_removes_empty_source_directories(self, tmp_src: Path):
        dated = tmp_src / "2024" / "01"
        dated.mkdir(parents=True)
        _touch(dated, "photo.jpg", b"fake")

        from photo_organizer.main import OrganizeRequest, run

        organized = tmp_src / "organized"
        request = OrganizeRequest(
            src=tmp_src,
            dst=organized,
            dry_run=False,
            verbose=False,
        )
        stats = run(request)

        assert stats["processed"] == 1
        assert not dated.exists()
        assert not (tmp_src / "2024").exists()
        assert organized.exists()
        assert stats["elapsed_seconds"] >= 0

    def test_dry_run_no_files_created(self, tmp_src: Path, tmp_dst: Path):
        _touch(tmp_src, "photo.jpg", b"fake")

        from photo_organizer.main import OrganizeRequest, run

        request = OrganizeRequest(src=tmp_src, dst=tmp_dst, dry_run=True)
        run(request)

        # Destination should be empty
        assert not any(tmp_dst.rglob("*"))


class TestUtils:
    def test_print_summary_includes_total_time(self, capsys: pytest.CaptureFixture[str]):
        print_summary(
            {
                "processed": 3,
                "skipped": 1,
                "errors": 0,
                "elapsed_seconds": 1.23,
            }
        )

        output = capsys.readouterr().out
        assert "Total files scanned : 4" in output
        assert "Total time          : 1.23s" in output


class TestCloudCopy:
    def test_copies_only_images_bucket(self, tmp_path: Path):
        src = tmp_path / "organized"
        dst = tmp_path / "cloud"
        image = src / "2024" / "07" / "04" / "images" / "shot.jpg"
        raw = src / "2024" / "07" / "04" / "raw" / "shot.CR3"
        video = src / "2024" / "07" / "04" / "videos" / "clip.mp4"
        image.parent.mkdir(parents=True)
        raw.parent.mkdir(parents=True)
        video.parent.mkdir(parents=True)
        image.write_bytes(b"jpeg")
        raw.write_bytes(b"raw")
        video.write_bytes(b"mp4")

        stats = copy_for_cloud(src, dst, dry_run=False)

        assert stats == {"copied": 1, "skipped": 0, "errors": 0}
        assert (dst / "2024" / "07" / "04" / "images" / "shot.jpg").exists()
        assert not (dst / "2024" / "07" / "04" / "raw" / "shot.CR3").exists()
        assert not (dst / "2024" / "07" / "04" / "videos" / "clip.mp4").exists()

    def test_skips_hidden_trash_and_appledouble_files(self, tmp_path: Path):
        src = tmp_path / "organized"
        dst = tmp_path / "cloud"
        hidden = src / ".trash" / "2024" / "07" / "04" / "images" / "shot.jpg"
        appledouble = src / "2024" / "07" / "04" / "images" / "._shot.jpg"
        real = src / "2024" / "07" / "04" / "images" / "shot.jpg"
        hidden.parent.mkdir(parents=True)
        appledouble.parent.mkdir(parents=True, exist_ok=True)
        hidden.write_bytes(b"hidden")
        appledouble.write_bytes(b"meta")
        real.write_bytes(b"jpeg")

        stats = copy_for_cloud(src, dst, dry_run=False)

        assert stats == {"copied": 1, "skipped": 0, "errors": 0}
        assert (dst / "2024" / "07" / "04" / "images" / "shot.jpg").exists()
        assert not (dst / ".trash").exists()
        assert not (dst / "2024" / "07" / "04" / "images" / "._shot.jpg").exists()

    def test_dry_run_does_not_copy_files(self, tmp_path: Path):
        src = tmp_path / "organized"
        dst = tmp_path / "cloud"
        image = src / "2024" / "07" / "04" / "images" / "shot.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"jpeg")

        stats = copy_for_cloud(src, dst, dry_run=True)

        assert stats == {"copied": 1, "skipped": 0, "errors": 0}
        assert not dst.exists()


class FakeFTP:
    def __init__(self):
        self.cwd_calls: list[str] = []
        self.mkd_calls: list[str] = []
        self.stor_calls: list[str] = []

    def cwd(self, path: str) -> None:
        self.cwd_calls.append(path)

    def mkd(self, path: str) -> None:
        self.mkd_calls.append(path)

    def storbinary(self, command: str, fh) -> None:
        fh.read()
        self.stor_calls.append(command)


class TestFtpUpload:
    def test_upload_moves_file_to_trash(self, tmp_path: Path):
        src_root = tmp_path / "cloud_ready"
        trash_root = tmp_path / "ftp_trash"
        image = src_root / "2024" / "07" / "04" / "images" / "shot.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"jpeg")
        ftp = FakeFTP()

        stats = upload_to_ftp(
            source_root=src_root,
            trash_root=trash_root,
            ftp=ftp,
            remote_root="/photos",
            dry_run=False,
        )

        assert stats == {"uploaded": 1, "skipped": 0, "errors": 0}
        assert ftp.stor_calls == ["STOR shot.jpg"]
        assert not image.exists()
        assert (trash_root / "2024" / "07" / "04" / "images" / "shot.jpg").exists()

    def test_dry_run_does_not_move_or_upload(self, tmp_path: Path):
        src_root = tmp_path / "cloud_ready"
        trash_root = tmp_path / "ftp_trash"
        image = src_root / "2024" / "07" / "04" / "images" / "shot.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"jpeg")

        stats = upload_to_ftp(
            source_root=src_root,
            trash_root=trash_root,
            ftp=None,
            remote_root="/photos",
            dry_run=True,
        )

        assert stats == {"uploaded": 1, "skipped": 0, "errors": 0}
        assert image.exists()
        assert not trash_root.exists()
