import importlib.util
import io
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("avatar_archive", Path(__file__).parents[1] / "deploy" / "avatar_archive.py")
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


def packed(*members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as target:
        for member in members:
            info, data = member if isinstance(member, tuple) else (member, None)
            target.addfile(info, io.BytesIO(data) if data is not None else None)
    output.seek(0)
    return output


def root_member():
    root = tarfile.TarInfo("avatars")
    root.type = tarfile.DIRTYPE
    return root


def file_member(name="avatars/user-abc.png", data=b"png contents"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


class AvatarArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.target = patch.object(archive, "AVATAR_DIR", self.root)
        self.target.start()

    def tearDown(self):
        self.target.stop()
        self.directory.cleanup()

    def test_round_trip_restores_snapshot_without_deleting_newer_orphans(self):
        (self.root / "user-abc.png").write_bytes(b"old avatar")
        output = io.BytesIO()
        archive.backup(output)
        output.seek(0)
        self.assertEqual(archive.read_archive(output), ["user-abc.png"])
        (self.root / "user-abc.png").write_bytes(b"new avatar")
        (self.root / "other-abc.png").write_bytes(b"retained orphan")
        output.seek(0)
        archive.restore(output)
        self.assertEqual((self.root / "user-abc.png").read_bytes(), b"old avatar")
        self.assertEqual((self.root / "other-abc.png").read_bytes(), b"retained orphan")
        self.assertFalse(any(path.name.startswith(".restore-") for path in self.root.iterdir()))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.root / "user-abc.png").stat().st_mode), 0o600)

    def test_empty_avatar_store_has_a_valid_snapshot(self):
        output = io.BytesIO()
        archive.backup(output)
        output.seek(0)
        self.assertEqual(archive.read_archive(output), [])

    def test_snapshot_includes_uploaded_and_shop_backgrounds(self):
        backgrounds = {"bg-owner-random.webp": b"background", "shop-stars.gif": b"animated background"}
        for name, image in backgrounds.items():
            (self.root / name).write_bytes(image)
        output = io.BytesIO()
        archive.backup(output)
        output.seek(0)
        self.assertEqual(archive.read_archive(output), sorted(backgrounds))

    def test_path_traversal_absolute_paths_nested_files_and_special_members_are_rejected(self):
        bad_names = ["/outside.png", "avatars/../outside.png", "avatars/a/evil.png", "avatars/..\\evil.png", "other/a.png"]
        for name in bad_names:
            with self.subTest(name=name), self.assertRaises(archive.ArchiveError):
                archive.read_archive(packed(root_member(), file_member(name)))
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]:
            info = tarfile.TarInfo("avatars/user-abc.png")
            info.type = kind
            info.linkname = "/outside"
            with self.subTest(kind=kind), self.assertRaises(archive.ArchiveError):
                archive.read_archive(packed(root_member(), info))

    def test_duplicate_names_missing_root_and_oversized_files_are_rejected(self):
        inputs = [packed(file_member()), packed(root_member(), file_member(), file_member()),
                  packed(root_member(), file_member(data=b"x" * (archive.MAX_FILE_BYTES + 1)))]
        for source in inputs:
            with self.assertRaises(archive.ArchiveError):
                archive.read_archive(source)

    def test_failed_validation_does_not_replace_any_live_avatar(self):
        path = self.root / "user-abc.png"
        path.write_bytes(b"current")
        with self.assertRaises(archive.ArchiveError):
            archive.restore(packed(root_member(), file_member(data=b"snapshot"), file_member("avatars/../../escape.png")))
        self.assertEqual(path.read_bytes(), b"current")

    def test_backup_skips_private_failed_restore_staging_but_rejects_unknown_live_files(self):
        (self.root / ".restore-stale").mkdir()
        (self.root / ".restore-stale" / "private.png").write_bytes(b"not live")
        (self.root / "user-abc.png").write_bytes(b"live")
        output = io.BytesIO()
        archive.backup(output)
        output.seek(0)
        self.assertEqual(archive.read_archive(output), ["user-abc.png"])
        (self.root / "unknown.txt").write_text("not an avatar")
        with self.assertRaises(archive.ArchiveError):
            archive.backup(io.BytesIO())


if __name__ == "__main__":
    unittest.main()
