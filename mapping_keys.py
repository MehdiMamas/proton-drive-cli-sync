"""Pure helpers for mapping dictionaries (no GUI imports, testable without a display)."""
__version__ = "1.1.0"   # version propre à CE fichier ; incrémentée quand il change (indépendant de GitHub)

# Keys the mapping dialog builds itself on every save. A key in this set that the
# dialog leaves out was deliberately switched off by the user and must NOT come back.
# excluded_remote est édité par la case du dialogue : décochée, la clé ne revient pas.
DIALOG_KEYS = frozenset({
    "type", "source", "dest_parent", "exclusions",
    "conflict_mode", "allow_delete", "delete_mode", "source_kind",
    "excluded_remote",
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

FILE_KEYS = frozenset({"exclusions", "mappings"})


def unknown_top_level(document):
    """Clés de premier niveau que l'éditeur ne gère pas, dans l'ordre du
    fichier. Un fichier au format liste n'en a pas."""
    if not isinstance(document, dict):
        return {}
    return {k: v for k, v in document.items() if k not in FILE_KEYS}
