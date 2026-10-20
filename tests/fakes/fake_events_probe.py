#!/usr/bin/env python3
"""Fake `proton-sync-events` probe.

Usage as the engine runs it: events changes -j [-k] <proton folder>

The scenario file (env FAKE_PROBE_SCRIPT) maps a Proton folder (or "*") to
{"initialized": bool, "changes": [...], "fail": bool, "garbage": bool}. Every
run is appended to FAKE_PROBE_LOG as one JSON line. A run without -k hands out
the changes and clears them, like a probe advancing its bookmark.
"""
import json
import os
import sys
import time


def main(argv):
    keep = "-k" in argv or "--keep" in argv
    folder = [a for a in argv[2:] if not a.startswith("-")][-1]
    state_dir = os.environ.get("PROTON_SYNC_EVENTS_DIR", "")
    log = os.environ["FAKE_PROBE_LOG"]
    entry = {"folder": folder, "keep": keep, "state_dir": state_dir,
             "isdir": os.path.isdir(state_dir)}
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(entry, event="start")) + "\n")
    time.sleep(0.15)
    path = os.environ["FAKE_PROBE_SCRIPT"]
    with open(path, encoding="utf-8") as fh:
        script = json.load(fh)
    scenario = script.get(folder, script.get("*", {}))
    out, code = None, 0
    if scenario.get("fail"):
        sys.stderr.write("probe failed\n")
        code = 3
    elif scenario.get("garbage"):
        out = "not json at all"
    else:
        out = json.dumps({
            "folder": folder, "initialized": scenario.get("initialized", True),
            "eventsRead": len(scenario.get("changes", [])),
            "changes": scenario.get("changes", []), "notes": [],
            "bookmarkAdvanced": not keep})
        if not keep:
            scenario["changes"] = []
            script[folder if folder in script else "*"] = scenario
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(script, fh)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(entry, event="end")) + "\n")
    if out is not None:
        print(out)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
