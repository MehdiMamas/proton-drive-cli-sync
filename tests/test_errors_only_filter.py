"""The “❗ Errors only” filter of the window.

Keywords (error, erreur, échec, failed) are looked for only before the first
“/” and the first “:”, so that a file NAME cannot make a line an error: a
SHA1 decision line shows the name alone, after a colon.
"""


def _line_is_error():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "proton_mapping_editor.py").read_text(encoding="utf-8")
    start = source.index("def line_is_error(")
    end = source.index("\ndef ", start + 10)
    namespace = {}
    exec(source[start:end], namespace)
    return namespace["line_is_error"]


def test_a_file_name_does_not_make_a_line_an_error():
    is_error = _line_is_error()
    for line in ("(taille identique, contenu vérifié par SHA1 — identique : Erreurs-2024.txt)",
                 "(same size, content checked by SHA1 — identical: error-log.txt)",
                 "(same size but different content: failed-backup.zip)"):
        assert not is_error(line), line
    for line in ("❌ upload failed: x.txt", "upload failed: x.txt",
                 "Erreur : le montage a disparu", "⚠  (orphan folder: x — size not measured, listing failed)"):
        assert is_error(line), line
