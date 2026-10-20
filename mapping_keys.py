"""Pure helpers for mapping dictionaries (no GUI imports, testable without a display)."""
__version__ = "1.2.0"   # version propre à CE fichier ; incrémentée quand il change (indépendant de GitHub)

import os

# Keys the mapping dialog builds itself on every save. A key in this set that the
# dialog leaves out was deliberately switched off by the user and must NOT come back.
# excluded_remote est édité par la case du dialogue : décochée, la clé ne revient pas.
DIALOG_KEYS = frozenset({
    "type", "source", "dest_parent", "exclusions",
    "conflict_mode", "allow_delete", "delete_mode", "source_kind",
    "excluded_remote", "_sync_mode",
})


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


# ── Dossiers d'arrivée sur Proton ────────────────────────────────────────────
# Un mapping dépose son contenu dans dest_parent/<nom de la source> : son
# « dossier d'arrivée ». Deux mappings dont les dossiers d'arrivée sont égaux,
# ou dont l'un est à l'intérieur de l'autre, se marchent dessus : quand les
# suppressions sont propagées, le moteur met à la corbeille tout ce qui, sur
# Proton, n'a pas d'équivalent dans SA source — donc le contenu de l'autre.
# Ce calcul unique sert au moteur (suppressions retenues) et à l'éditeur
# (avertissement au chargement, refus d'un nouveau conflit).

def arrival_folder(mapping):
    """Dossier du Drive où le mapping dépose son contenu, ou None si la source
    ou la destination manque. Même calcul que le moteur :
    dest_parent sans « / » final, plus le nom de la source."""
    dest = (mapping.get("dest_parent") or "").strip().rstrip("/")
    src = (mapping.get("source") or "").strip().rstrip("/")
    if not dest or not src:
        return None
    name = src.rsplit("/", 1)[-1]
    if not name:
        return None
    parts = [p for p in (dest + "/" + name).split("/") if p and p != "."]
    return "/" + "/".join(parts)


def _inside(inner, outer):
    return inner.startswith(outer + "/")


def conflict_kind(a, b):
    """Relation entre deux dossiers d'arrivée : "same", "a_in_b", "b_in_a"
    ou None (aucun conflit). Comparaison à frontière de segment :
    /x/Doc n'est pas dans /x/Documents."""
    if a is None or b is None:
        return None
    if a == b:
        return "same"
    if _inside(a, b):
        return "a_in_b"
    if _inside(b, a):
        return "b_in_a"
    return None


def arrival_conflicts(mappings):
    """Toutes les paires en conflit d'une liste de mappings.

    Retourne une liste de (outer, inner, kind, outer_folder, inner_folder),
    où outer et inner sont des INDICES dans `mappings` :
      - kind "same" : même dossier d'arrivée (outer < inner, ordre du fichier) ;
      - kind "nested" : le dossier d'arrivée de inner est dans celui de outer.
    """
    folders = [arrival_folder(m) if isinstance(m, dict) else None for m in mappings]
    out = []
    for i in range(len(mappings)):
        for j in range(i + 1, len(mappings)):
            kind = conflict_kind(folders[i], folders[j])
            if kind == "same":
                out.append((i, j, "same", folders[i], folders[j]))
            elif kind == "b_in_a":
                out.append((i, j, "nested", folders[i], folders[j]))
            elif kind == "a_in_b":
                out.append((j, i, "nested", folders[j], folders[i]))
    return out


def deletion_holds(mappings):
    """Indices des mappings dont les suppressions doivent être retenues, avec,
    pour chacun, l'indice d'un mapping en conflit (le premier trouvé).

    Les DEUX mappings de chaque paire, imbriquée comme identique. Pour une
    paire imbriquée, celui qui contient l'autre jetterait son contenu ; mais
    celui qui est à l'intérieur peut aussi jeter des fichiers de l'autre :
    quand la source englobante a un sous-dossier du même nom, les deux
    envoient dans le même dossier distant (démontré sur le faux Drive)."""
    holds = {}
    for outer, inner, _kind, _fo, _fi in arrival_conflicts(mappings):
        holds.setdefault(outer, inner)
        holds.setdefault(inner, outer)
    return holds


def first_arrival_conflict(candidate, others):
    """Premier conflit entre `candidate` et la liste `others`, ou None.
    Retourne (other, kind, candidate_folder, other_folder), kind valant
    "same", "inside" (le candidat arrive dans le dossier de l'autre) ou
    "contains" (l'autre arrive dans le dossier du candidat)."""
    mine = arrival_folder(candidate)
    if mine is None:
        return None
    for other in others:
        if not isinstance(other, dict):
            continue
        theirs = arrival_folder(other)
        kind = conflict_kind(mine, theirs)
        if kind is None:
            continue
        return (other, {"same": "same", "a_in_b": "inside", "b_in_a": "contains"}[kind],
                mine, theirs)
    return None


# ── Clés de premier niveau du fichier de mappings ────────────────────────────
# L'éditeur ne gère que "exclusions" et "mappings". Une version plus récente
# peut écrire d'autres clés dans le même fichier (ex. "sync_mappings") : elles
# doivent survivre à un enregistrement fait par cette version, sans que
# celle-ci en tienne compte autrement.

FILE_KEYS = frozenset({"exclusions", "mappings", "sync_mappings"})


def unknown_top_level(document):
    """Clés de premier niveau que l'éditeur ne gère pas, dans l'ordre du
    fichier. Un fichier au format liste n'en a pas."""
    if not isinstance(document, dict):
        return {}
    return {k: v for k, v in document.items() if k not in FILE_KEYS}


# ── Mappings deux sens (clé "sync_mappings") ─────────────────────────────────
# Un mapping deux sens ne doit chevaucher AUCUN autre mapping (à sens unique ou
# deux sens), ni en local (même dossier, parent, sous-dossier), ni sur Proton
# (règle des dossiers d'arrivée ci-dessus). Les mappings à sens unique, eux,
# gardent leur comportement : ils peuvent se chevaucher entre eux.

SYNC_DIRECTIONS = ("twoway",)
SYNC_TYPES = ("folder", "file")


def _local_path(mapping):
    src = (mapping.get("source") or "").strip() if isinstance(mapping, dict) else ""
    if not src:
        return None
    return os.path.normpath(src)


def local_overlap(a, b):
    """Relation locale entre deux mappings : "same", "parent" (a contient b),
    "child" (a est dans b) ou None. Comparaison à frontière de segment."""
    pa, pb = _local_path(a), _local_path(b)
    if pa is None or pb is None:
        return None
    if pa == pb:
        return "same"
    if pb.startswith(pa.rstrip("/") + "/"):
        return "parent"
    if pa.startswith(pb.rstrip("/") + "/"):
        return "child"
    return None


def sync_mapping_conflicts(sync_mappings, upload_mappings=()):
    """Mappings deux sens en conflit, à vérifier à chaque chargement du fichier.

    `sync_mappings` : la liste de la clé "sync_mappings" ; `upload_mappings` :
    celle de "mappings". Retourne {indice dans sync_mappings: (raison, autre
    mapping, détail)}, au premier conflit trouvé pour chaque mapping. La raison
    vaut "local-same", "local-parent" (ce mapping contient l'autre),
    "local-child" (il est dans l'autre), ou "arrival-same", "arrival-inside",
    "arrival-contains" (dossiers d'arrivée sur Proton) ; le détail est le
    dossier d'arrivée de l'autre pour ces trois dernières, "" sinon.
    Un élément qui n'est pas un dict est ignoré."""
    out = {}
    pool = [(("sync", i), m) for i, m in enumerate(sync_mappings or ())
            if isinstance(m, dict)]
    pool += [(("up", i), m) for i, m in enumerate(upload_mappings or ())
             if isinstance(m, dict)]
    for (kind, i), m in pool:
        if kind != "sync":
            continue
        others = [o for key, o in pool if key != (kind, i)]
        found = None
        for o in others:
            rel = local_overlap(m, o)
            if rel:
                found = ("local-" + rel, o, "")
                break
        if found is None:
            hit = first_arrival_conflict(m, others)
            if hit:
                other, rel, _mine, theirs = hit
                found = ("arrival-" + rel, other, theirs)
        if found:
            out[i] = found
    return out


# ── Sync mode in the editor (upload vs two-way) ──────────────────────────────
# In memory the editor holds one flat list. A two-way mapping carries the marker
# _sync_mode = "twoway"; the marker is never written. In the file the mode is
# given by the list: "mappings" (upload) or "sync_mappings" (two-way, with
# "direction": "twoway"). Every other key of a mapping travels untouched.

MODE_KEY = "_sync_mode"
MODE_UPLOAD = "upload"
MODE_TWOWAY = "twoway"
DIRECTION_KEY = "direction"


def sync_mode(mapping):
    """MODE_TWOWAY or MODE_UPLOAD (default) for an in-memory mapping."""
    return MODE_TWOWAY if mapping.get(MODE_KEY) == MODE_TWOWAY else MODE_UPLOAD


def set_sync_mode(mapping, mode):
    """Set the mode on `mapping` in place (upload = no marker). Returns it.
    Moving to upload also drops direction "twoway", which only belongs in
    sync_mappings; a mapping moving to two-way gets it when saved."""
    if mode == MODE_TWOWAY:
        mapping[MODE_KEY] = MODE_TWOWAY
    else:
        mapping.pop(MODE_KEY, None)
        if mapping.get(DIRECTION_KEY) == "twoway":
            mapping.pop(DIRECTION_KEY, None)
    return mapping


def split_loaded(data):
    """Split the JSON of a mappings file.

    Returns (mappings, global_exclusions, extras): `mappings` is "mappings"
    followed by "sync_mappings" (marked MODE_TWOWAY), `extras` the top-level
    keys the editor does not manage, to be written back as they are (a
    "sync_mappings" that is not a list stays in extras, untouched).
    Raises ValueError for an unknown format."""
    if isinstance(data, list):
        return list(data), {"names": [], "patterns": []}, {}
    if not isinstance(data, dict):
        raise ValueError("The file must contain a list or an object.")
    up = data.get("mappings", []) or []
    tw = data.get("sync_mappings", []) or []
    extras = unknown_top_level(data)
    if not isinstance(tw, list):
        extras["sync_mappings"] = data["sync_mappings"]
        tw = []
    mappings = list(up)
    for entry in tw:
        if isinstance(entry, dict):
            entry = dict(entry)
            entry[MODE_KEY] = MODE_TWOWAY
        mappings.append(entry)
    ex = data.get("exclusions", {}) or {}
    global_ex = {"names": list(ex.get("names", []) or []),
                 "patterns": list(ex.get("patterns", []) or [])}
    return mappings, global_ex, extras


def split_by_mode(mappings):
    """(upload, twoway) lists of clean copies (marker removed, direction set)."""
    upload, twoway = [], []
    for m in mappings:
        clean = {k: v for k, v in m.items() if k != MODE_KEY}
        if sync_mode(m) == MODE_TWOWAY:
            clean.setdefault(DIRECTION_KEY, "twoway")
            twoway.append(clean)
        else:
            if clean.get(DIRECTION_KEY) == "twoway":
                del clean[DIRECTION_KEY]
            upload.append(clean)
    return upload, twoway


def build_output(mappings, global_ex=None, extras=None):
    """JSON content to write. Keeps the historic plain-list format while there
    is no exclusion, no two-way mapping and no unknown top-level key; otherwise
    an object. Relative order is kept inside each list."""
    global_ex = global_ex or {}
    extras = extras or {}
    upload, twoway = split_by_mode(mappings)
    has_global = bool(global_ex.get("names") or global_ex.get("patterns"))
    has_mapping_excl = any(m.get("exclusions") for m in mappings)
    if not (has_global or has_mapping_excl or twoway or extras):
        return upload
    out = {"exclusions": {"names": global_ex.get("names", []),
                          "patterns": global_ex.get("patterns", [])}}
    out["mappings"] = upload
    if twoway:
        out["sync_mappings"] = twoway
    for k, v in extras.items():
        out.setdefault(k, v)
    return out


def twoway_conflicts(mappings):
    """Run sync_mapping_conflicts on the editor's flat list. Returns a list of
    (index in `mappings`, reason, other_mapping, detail), in list order."""
    tw_idx = [i for i, m in enumerate(mappings)
              if isinstance(m, dict) and sync_mode(m) == MODE_TWOWAY]
    up = [m for m in mappings if isinstance(m, dict) and sync_mode(m) != MODE_TWOWAY]
    found = sync_mapping_conflicts([mappings[i] for i in tw_idx], up)
    return [(tw_idx[k], *found[k]) for k in sorted(found)]
