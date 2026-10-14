"""The “Create thumbnails for images and videos” setting.

On by default: uploads carry no option, the CLI makes its thumbnails as it
always did. Off: every upload passes `--skip-thumbnails`, before `--` so the
CLI does not take it for a file name.
"""


def _mapping(source):
    return {"type": "folder", "source": str(source), "dest_parent": "/my-files/Backups"}


def _upload_argvs(fake_drive):
    return [c["argv"] for c in fake_drive.upload_cwds()]


def test_thumbnails_on_by_default(fake_drive, local_tree, write_mappings, engine):
    src = local_tree({"Photos/a.jpg": (b"a", 1_000_000_000)})
    result = engine(write_mappings([_mapping(src / "Photos")]))
    assert result.returncode == 0, result.stdout + result.stderr
    argvs = _upload_argvs(fake_drive)
    assert argvs
    assert all("--skip-thumbnails" not in a for a in argvs)


def test_unchecked_box_skips_thumbnails_on_every_upload(
        fake_drive, local_tree, write_mappings, engine):
    engine.update_settings(create_thumbnails=False)
    src = local_tree({"Photos/a.jpg": (b"a", 1_000_000_000),
                      "Photos/-b.jpg": (b"b", 1_000_000_000)})
    result = engine(write_mappings([_mapping(src / "Photos")]))
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.content("/my-files/Backups/Photos/a.jpg") == b"a"
    assert fake_drive.content("/my-files/Backups/Photos/-b.jpg") == b"b"
    argvs = _upload_argvs(fake_drive)
    assert argvs
    for a in argvs:
        assert "--skip-thumbnails" in a
        assert a.index("--skip-thumbnails") < a.index("--")


def test_unreadable_value_keeps_thumbnails():
    import config
    config._put("create_thumbnails", "maybe")
    assert config.create_thumbnails() is True
    config._put("create_thumbnails", "off")
    assert config.create_thumbnails() is False
    assert config.set_create_thumbnails(True) is not False
    assert config.create_thumbnails() is True
