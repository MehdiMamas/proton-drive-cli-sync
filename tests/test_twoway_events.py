"""The "events" trigger: a probe reports what changed on Proton, the engine
reconciles only that, and falls back to a full listing when the probe cannot
be trusted."""

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

import remote_state

REMOTE = "/my-files/B"
FAKE = Path(__file__).parent / "fakes" / "fake_events_probe.py"


def _mapping(source):
    return {"type": "folder", "source": str(source), "dest_parent": REMOTE,
            "direction": "twoway", "allow_delete": True, "source_kind": "local"}


def _verb(calls, verb):
    return [c for c in calls if len(c) >= 2 and c[0] == "filesystem" and c[1] == verb]


class Probe:
    def __init__(self, tmp_path, monkeypatch, engine):
        self.script = tmp_path / "probe-script.json"
        self.log = tmp_path / "probe.log"
        self.script.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("FAKE_PROBE_SCRIPT", str(self.script))
        monkeypatch.setenv("FAKE_PROBE_LOG", str(self.log))
        engine.update_settings(
            twoway_trigger="events",
            twoway_probe_cmd="{} {}".format(shlex.quote(sys.executable), shlex.quote(str(FAKE))))
        self.engine = engine

    def set(self, scenario, folder="*"):
        data = json.loads(self.script.read_text(encoding="utf-8"))
        data[folder] = scenario
        self.script.write_text(json.dumps(data), encoding="utf-8")

    def runs(self):
        if not self.log.exists():
            return []
        rows = [json.loads(x) for x in self.log.read_text().splitlines()]
        return [r for r in rows if r["event"] == "start"]

    def events(self):
        if not self.log.exists():
            return []
        return [json.loads(x) for x in self.log.read_text().splitlines()]


@pytest.fixture
def probe(tmp_path, monkeypatch, engine):
    return Probe(tmp_path, monkeypatch, engine)


def _first_sync(engine, local_tree, write_mappings, files):
    """Baseline with the default trigger, then switch to events."""
    src = local_tree(files)
    cfg = write_mappings([_mapping(src / "Docs")])
    engine.update_settings(twoway_trigger="none")
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    return src, cfg


def _use_events(engine, probe):
    engine.update_settings(twoway_trigger="events")


def _rename_nodes(fake_drive, old, new):
    old, new = remote_state.normalize(old), remote_state.normalize(new)

    def mutate(state):
        remote_state.ensure_folders(state, new)
        nodes = state["nodes"]
        for path in sorted(nodes):
            if path == old or path.startswith(old + "/"):
                nodes[new + path[len(old):]] = nodes.pop(path)
    fake_drive._update(mutate)


def _trash(fake_drive, path):
    path = remote_state.normalize(path)

    def mutate(state):
        state["nodes"][path]["trashed"] = True
    fake_drive._update(mutate)


def _setup(engine, probe, local_tree, write_mappings, files):
    src, cfg = _first_sync(engine, local_tree, write_mappings, files)
    _use_events(engine, probe)
    return src, cfg


def test_default_trigger_never_runs_the_probe(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _first_sync(engine, local_tree, write_mappings,
                           {"Docs/a.txt": b"AAAA"})
    probe.set({"initialized": True, "changes": []})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert probe.runs() == []


def test_command_line_and_state_dir(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    probe.set({"initialized": True, "changes": []})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    runs = probe.runs()
    assert [r["keep"] for r in runs] == [True, False]  # read, then acknowledge
    assert runs[0]["folder"] == REMOTE + "/Docs"
    assert runs[0]["state_dir"].endswith(os.path.join("events-probe", runs[0]["state_dir"].split(os.sep)[-1]))


def test_moved_is_renamed_here_without_download_then_acknowledged(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA", "Docs/sub/c.txt": b"CCCC"})
    _rename_nodes(fake_drive, REMOTE + "/Docs/a.txt", REMOTE + "/Docs/b.txt")
    probe.set({"initialized": True, "changes": [
        {"action": "moved", "type": "file", "path": "b.txt", "from": "a.txt"}]})
    before = len(_verb(fake_drive.calls(), "download"))
    seen = len(fake_drive.calls())
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(os.listdir(src / "Docs")) == ["b.txt", "sub"]
    assert (src / "Docs" / "b.txt").read_bytes() == b"AAAA"
    assert len(_verb(fake_drive.calls(), "download")) == before
    assert [r["keep"] for r in probe.runs()] == [True, False]
    # the subfolder was not listed: only the folders concerned are
    lists = [c for c in fake_drive.calls()[seen:] if len(c) >= 2 and c[1] == "list"]
    assert lists and not any(REMOTE + "/Docs/sub" in " ".join(c) for c in lists)


def test_remote_change_is_applied_and_unreported_ones_wait_for_a_full_pass(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    fake_drive.seed_file(REMOTE + "/Docs/new.txt", b"NEW")
    fake_drive.seed_file(REMOTE + "/Docs/unreported.txt", b"XX")
    probe.set({"initialized": True, "changes": [
        {"action": "created", "type": "file", "path": "new.txt"}]})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    # the folder is reconciled as a whole once the probe names it
    assert (src / "Docs" / "new.txt").read_bytes() == b"NEW"
    assert [r["keep"] for r in probe.runs()] == [True, False]


def test_nothing_reported_means_remote_folders_are_not_listed(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    fake_drive.seed_file(REMOTE + "/Docs/silent.txt", b"S")
    probe.set({"initialized": True, "changes": []})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (src / "Docs" / "silent.txt").exists()


def test_local_change_is_uploaded_without_a_reported_event(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    local_tree.write("Docs/mine.txt", b"MINE", 1_000_000_100)
    probe.set({"initialized": True, "changes": []})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert fake_drive.content(REMOTE + "/Docs/mine.txt") == b"MINE"


def test_removed_keeps_local_copy_without_delete(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    _trash(fake_drive, REMOTE + "/Docs/a.txt")
    probe.set({"initialized": True, "changes": [
        {"action": "removed", "type": "file", "path": "a.txt"}]})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "a.txt").exists()
    assert _verb(fake_drive.calls(), "trash") == []


def test_removed_with_delete_goes_through_the_guarded_path(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA", "Docs/b.txt": b"BBBB",
                       "Docs/c.txt": b"CCCC"})
    _trash(fake_drive, REMOTE + "/Docs/a.txt")
    probe.set({"initialized": True, "changes": [
        {"action": "removed", "type": "file", "path": "a.txt"}]})
    result = engine(cfg, "--delete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (src / "Docs" / "a.txt").exists()
    assert (src / "Docs" / "b.txt").exists()


def test_no_acknowledge_when_the_apply_fails(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    fake_drive.seed_file(REMOTE + "/Docs/new.txt", b"NEW")
    fake_drive.add_fault(cmd="list", match=REMOTE + "/Docs")
    probe.set({"initialized": True, "changes": [
        {"action": "created", "type": "file", "path": "new.txt"}]})
    engine(cfg)
    assert [r["keep"] for r in probe.runs()] == [True]


def test_dry_run_does_not_acknowledge(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    fake_drive.seed_file(REMOTE + "/Docs/new.txt", b"NEW")
    probe.set({"initialized": True, "changes": [
        {"action": "created", "type": "file", "path": "new.txt"}]})
    result = engine(cfg, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [r["keep"] for r in probe.runs()] == [True]


@pytest.mark.parametrize("scenario", [
    {"fail": True},
    {"garbage": True},
    {"initialized": False, "changes": []},
])
def test_probe_trouble_falls_back_to_full_listing(
        scenario, fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    fake_drive.seed_file(REMOTE + "/Docs/found.txt", b"F")
    probe.set(scenario)
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "found.txt").read_bytes() == b"F"
    assert result.stdout.count("[probe-fallback]") == 1
    assert [r["keep"] for r in probe.runs()] == [True]  # no acknowledge


def test_missing_probe_binary_falls_back_to_full_listing(
        fake_drive, local_tree, write_mappings, engine, probe):
    src, cfg = _setup(engine, probe, local_tree, write_mappings,
                      {"Docs/a.txt": b"AAAA"})
    engine.update_settings(twoway_probe_cmd="/nonexistent/proton-sync-events")
    fake_drive.seed_file(REMOTE + "/Docs/found.txt", b"F")
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "found.txt").read_bytes() == b"F"
    assert result.stdout.count("[probe-fallback]") == 1


def test_first_run_without_baseline_lists_everything(
        fake_drive, local_tree, write_mappings, engine, probe):
    src = local_tree({"Docs/a.txt": b"AAAA"})
    cfg = write_mappings([_mapping(src / "Docs")])
    fake_drive.seed_file(REMOTE + "/Docs/r.txt", b"R")
    engine.update_settings(twoway_trigger="events")
    probe.set({"initialized": True, "changes": []})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (src / "Docs" / "r.txt").read_bytes() == b"R"
    assert fake_drive.content(REMOTE + "/Docs/a.txt") == b"AAAA"


def test_one_state_dir_per_mapping_and_probes_never_overlap(
        fake_drive, local_tree, write_mappings, engine, probe):
    src = local_tree({"Docs/a.txt": b"AAAA", "Other/o.txt": b"OOOO"})
    cfg = write_mappings([_mapping(src / "Docs"), _mapping(src / "Other")])
    engine.update_settings(twoway_trigger="none")
    assert engine(cfg).returncode == 0
    engine.update_settings(twoway_trigger="events")
    probe.set({"initialized": True, "changes": []})
    result = engine(cfg)
    assert result.returncode == 0, result.stdout + result.stderr
    runs = probe.runs()
    assert len({r["state_dir"] for r in runs}) == 2
    assert {r["folder"] for r in runs} == {REMOTE + "/Docs", REMOTE + "/Other"}
    open_now = 0
    for ev in probe.events():
        open_now += 1 if ev["event"] == "start" else -1
        assert open_now <= 1
