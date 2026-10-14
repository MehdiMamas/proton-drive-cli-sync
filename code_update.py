"""code_update.py — Relance automatique après une mise à jour du code.

Un programme qui tourne longtemps (consommateur temps réel, watcher local,
icône, éditeur) garde en mémoire le code qu'il a chargé au démarrage. Quand de
nouveaux fichiers sont déposés dans le dossier de l'application, il continue
d'exécuter l'ancien code jusqu'à ce qu'on le relance — et rien ne le disait
(constaté en production : l'icône ne s'arrêtait plus quand on décochait la
case, le temps réel recréait un fichier de réglages à l'ancien emplacement).

Ce module :
  • relève l'EMPREINTE du code au démarrage : nom, date (ns) et taille de
    chaque .py du dossier de l'application et de chaque catalogue .mo ;
  • dit quand le code a changé ET que le dépôt est terminé : l'empreinte
    différente doit rester identique pendant STABLE_SECONDS. On ne se fie PAS
    à la date des fichiers : unzip et cp -p restituent les dates d'origine,
    si bien qu'un dépliement en cours peut poser des fichiers « vieux » d'une
    heure. Seule l'observation d'une empreinte qui ne bouge plus est sûre ;
  • refuse de se relancer sur un code qui ne se compile pas (fichier tronqué,
    dépôt incomplet) : le programme garde alors l'ancien code et réessaie
    au changement suivant. Un programme non surveillé (l'icône) qui se
    relancerait sur un code cassé disparaîtrait sans prévenir ;
  • inscrit chaque relance dans RESTARTS_FILE (une ligne JSON par relance,
    écrite en ajout : plusieurs programmes peuvent y écrire en même temps),
    pour que l'éditeur affiche une fois « Mise à jour appliquée » ;
  • relance le programme par-dessus lui-même (os.execv) : même numéro de
    processus, systemd ne voit ni arrêt ni échec.

Aucun texte affiché ici : l'éditeur traduit les noms de programmes.
Aucune dépendance obligatoire : sans config.py, le fichier d'état retombe sur
l'emplacement par défaut.
"""
__version__ = "1.0.0"   # version propre à CE fichier ; incrémentée quand il change (indépendant de GitHub)

import glob
import json
import os
import py_compile
import sys
import tempfile
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import config as _appconfig
    _DATA_DIR = _appconfig.DATA_DIR
except Exception:
    _DATA_DIR = os.path.expanduser("~/.proton-drive-sync")

RESTARTS_FILE = os.path.join(_DATA_DIR, "restarts.jsonl")

STABLE_SECONDS = 60

# Noms connus des programmes (clés écrites dans RESTARTS_FILE).
CONSUMER = "consumer"
WATCHER = "watcher"
TRAY = "tray"
EDITOR = "editor"


def code_files(app_dir=APP_DIR):
    """Fichiers dont le changement justifie une relance : les .py du dossier
    de l'application (pas les sous-dossiers : tests, outils) et les .mo."""
    files = glob.glob(os.path.join(app_dir, "*.py"))
    files += glob.glob(os.path.join(app_dir, "locale", "*", "LC_MESSAGES", "*.mo"))
    return sorted(files)


def fingerprint(app_dir=APP_DIR):
    """Empreinte du code : tuple trié (chemin relatif, date ns, taille).
    Un fichier qui disparaît pendant la lecture est simplement omis."""
    out = []
    for path in code_files(app_dir):
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append((os.path.relpath(path, app_dir), st.st_mtime_ns, st.st_size))
    return tuple(out)


def _compiles(app_dir):
    """True si tous les .py du dossier se compilent. Compilation dans un
    fichier jetable : on ne touche pas à __pycache__ du dossier."""
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(glob.glob(os.path.join(app_dir, "*.py"))):
            try:
                py_compile.compile(path, cfile=os.path.join(tmp, f"{i}.pyc"),
                                   doraise=True)
            except (py_compile.PyCompileError, OSError, ValueError):
                return False
    return True


class CodeWatch:
    """Surveille le code chargé par CE processus.

    ready() est bon marché (lecture des dates d'une trentaine de fichiers) et
    s'appelle là où le programme est au repos : entre deux cycles, à un
    relevé périodique. Il ne relance rien lui-même : le programme sort
    proprement de sa boucle, puis appelle restart()."""

    def __init__(self, name, app_dir=APP_DIR, stable_seconds=STABLE_SECONDS,
                 clock=time.monotonic):
        self.name = name
        self.app_dir = app_dir
        self.stable_seconds = stable_seconds
        self._clock = clock
        self._loaded = fingerprint(app_dir)
        self._seen = self._loaded
        self._since = None
        self._refused = None    # empreinte déjà jugée non compilable

    def changed(self):
        """Le code sur disque diffère-t-il de celui chargé ? (sans délai)"""
        return fingerprint(self.app_dir) != self._loaded

    def ready(self):
        now = self._clock()
        current = fingerprint(self.app_dir)
        if current == self._loaded:
            self._seen, self._since = current, None
            return False
        if current != self._seen or self._since is None:
            # Nouveau changement (ou dépôt encore en cours) : on repart à zéro.
            self._seen, self._since = current, now
            return False
        if now - self._since < self.stable_seconds:
            return False
        if current == self._refused:
            return False
        if not _compiles(self.app_dir):
            self._refused = current
            return False
        return True

    def restart(self, argv=None):
        """Inscrit la relance puis remplace le processus. Ne revient pas,
        sauf si execv échoue (on continue alors avec l'ancien code)."""
        record_restart(self.name)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        args = list(argv if argv is not None else sys.argv)
        if args:
            args[0] = os.path.abspath(args[0])
        os.execv(sys.executable, [sys.executable] + args)


def record_restart(name, when=None):
    """Ajoute une ligne {"name", "time"} à RESTARTS_FILE. Ne lève jamais."""
    line = json.dumps({"name": name, "time": when if when is not None else time.time()})
    try:
        os.makedirs(os.path.dirname(RESTARTS_FILE), exist_ok=True)
        fd = os.open(RESTARTS_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def take_restarts():
    """Lit ET retire les relances inscrites. Le fichier est d'abord renommé
    (opération atomique) : une relance inscrite pendant la lecture va dans un
    nouveau fichier et sera montrée la fois suivante, jamais perdue.
    Retourne une liste de dicts triée par heure ; [] si rien ou illisible."""
    taken = RESTARTS_FILE + ".taken"
    try:
        os.replace(RESTARTS_FILE, taken)
    except OSError:
        return []
    out = []
    try:
        with open(taken, encoding="utf-8") as fh:
            for raw in fh:
                try:
                    item = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    out.append(item)
    except OSError:
        pass
    try:
        os.remove(taken)
    except OSError:
        pass
    out.sort(key=lambda d: d.get("time") or 0)
    return out
