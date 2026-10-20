"""Pure helpers for mapping dictionaries (no GUI imports, testable without a display)."""
__version__ = "1.0.0"   # version propre à CE fichier ; incrémentée quand il change (indépendant de GitHub)

# Keys the mapping dialog builds itself on every save. A key in this set that the
# dialog leaves out was deliberately switched off by the user and must NOT come back.
# excluded_remote est édité par la case du dialogue : décochée, la clé ne revient pas.
DIALOG_KEYS = frozenset({
    "type", "source", "dest_parent", "exclusions",
    "conflict_mode", "allow_delete", "delete_mode", "source_kind",
    "excluded_remote", "_sync_mode",
})

# Mode de synchro, EN MÉMOIRE seulement : un mapping deux sens porte
# _sync_mode = "twoway" dans l'éditeur ; la clé n'est jamais écrite. Dans le
# fichier, le mode est donné par la liste : "mappings" (envoi seul) ou
# "twoway_mappings" (deux sens).
MODE_KEY = "_sync_mode"
MODE_UPLOAD = "upload"
MODE_TWOWAY = "twoway"
# Clés du niveau supérieur que l'éditeur gère lui-même.
TOP_KEYS = frozenset({"mappings", "twoway_mappings", "exclusions"})


def sync_mode(mapping):
    """MODE_TWOWAY ou MODE_UPLOAD (défaut) pour un mapping en mémoire."""
    return MODE_TWOWAY if mapping.get(MODE_KEY) == MODE_TWOWAY else MODE_UPLOAD


def set_sync_mode(mapping, mode):
    """Pose le mode sur `mapping` (envoi seul = pas de clé). Retourne `mapping`."""
    if mode == MODE_TWOWAY:
        mapping[MODE_KEY] = MODE_TWOWAY
    else:
        mapping.pop(MODE_KEY, None)
    return mapping


def split_loaded(data):
    """Décompose le JSON d'un fichier de mappings.

    Retourne (mappings, global_exclusions, extras) : `mappings` = ceux de
    "mappings" puis ceux de "twoway_mappings" (marqués MODE_TWOWAY), `extras` =
    les clés inconnues du niveau supérieur, à réécrire telles quelles.
    Lève ValueError si le format n'est pas reconnu.
    """
    if isinstance(data, list):
        return list(data), {"names": [], "patterns": []}, {}
    if not isinstance(data, dict):
        raise ValueError("The file must contain a list or an object.")
    up = data.get("mappings", []) or []
    tw = data.get("twoway_mappings", []) or []
    if not isinstance(up, list) or not isinstance(tw, list):
        raise ValueError("The file must contain a list or an object.")
    mappings = list(up)
    for entry in tw:
        if isinstance(entry, dict):
            entry = dict(entry)
            entry[MODE_KEY] = MODE_TWOWAY
        mappings.append(entry)
    ex = data.get("exclusions", {}) or {}
    global_ex = {"names": list(ex.get("names", []) or []),
                 "patterns": list(ex.get("patterns", []) or [])}
    extras = {k: v for k, v in data.items() if k not in TOP_KEYS}
    return mappings, global_ex, extras


def build_output(mappings, global_ex=None, extras=None):
    """Contenu JSON à écrire. Garde le format « liste simple » historique tant
    qu'il n'y a ni exclusion, ni mapping deux sens, ni clé inconnue au niveau
    supérieur ; sinon objet. L'ordre relatif des mappings est conservé dans
    chaque liste."""
    global_ex = global_ex or {}
    extras = extras or {}
    upload, twoway = [], []
    for m in mappings:
        clean = {k: v for k, v in m.items() if k != MODE_KEY}
        (twoway if sync_mode(m) == MODE_TWOWAY else upload).append(clean)
    has_global = bool(global_ex.get("names") or global_ex.get("patterns"))
    has_mapping_excl = any(m.get("exclusions") for m in mappings)
    if not (has_global or has_mapping_excl or twoway or extras):
        return upload
    out = {}
    if has_global or has_mapping_excl:
        out["exclusions"] = {"names": global_ex.get("names", []),
                             "patterns": global_ex.get("patterns", [])}
    out["mappings"] = upload
    if twoway:
        out["twoway_mappings"] = twoway
    for k, v in extras.items():
        out[k] = v
    return out


def carry_unknown_keys(old, new):
    """Copy to `new` every key of `old` that the dialog does not manage
    (future keys...). Returns `new`. Keys already present in `new` are never
    overwritten. excluded_remote is a dialog key: an unchecked box must not
    come back from the previous mapping."""
    if not old:
        return new
    for key, value in old.items():
        if key not in DIALOG_KEYS and key not in new:
            new[key] = value
    return new
