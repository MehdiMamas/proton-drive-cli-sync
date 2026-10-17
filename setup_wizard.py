#!/usr/bin/env python3
"""
Assistant de démarrage — de la première ouverture jusqu'au système qui
n'attend plus que des mappings.

Pages : accueil, CLI, connexion à Proton, mode (local seul ou avec un NAS),
dossier partagé du NAS, correspondances, watcher du NAS, planification et
temps réel, fin. Chaque page VÉRIFIE avant de laisser passer à la suivante ;
rien n'est supposé réussi. Ce qui se fait sur le NAS reste manuel (pas de SSH,
il faut sudo) : l'assistant donne la commande exacte, puis attend que le
watcher réponde.

Ce module ne réimplémente rien : il appelle la logique existante (config,
realtime_manager, schedule_manager, le moteur pour la version du CLI) et les
dialogues de l'éditeur (connexion, boîtes de message, sélecteurs). L'éditeur
le passe en `ui` (son propre module), ce qui évite tout import circulaire.

Ouverture : seul au premier lancement (aucun settings.json), sinon par le
bouton « Setup assistant… » de l'éditeur, ou proposé aux pages du NAS quand
on coche « Use a NAS » dans la Configuration.
"""
__version__ = "1.0.2"   # version propre à CE fichier ; incrémentée quand il change (indépendant de GitHub)

import getpass
import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

try:
    from i18n import _
except ImportError:
    def _(s):
        return s

import config as appconfig
import realtime_manager
import schedule_manager

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CLI_DOWNLOAD_URL = "https://proton.me/download/drive/cli/index.html"

GREEN, YELLOW, RED, GREY, BLUE = "#22c55e", "#eab308", "#ef4444", "#9ca3af", "#3b82f6"
MUTED = "#555577"

# Ordre des pages. « nas » ouvre l'assistant directement au dossier partagé
# (activation du NAS sur une installation existante).
PAGES = ["welcome", "cli", "login", "mode", "shared", "pairs", "watcher",
         "services", "done"]
START_AT = {"welcome": "welcome", "nas": "shared"}


def default_mappings_path():
    """Fichier de mappings créé par l'assistant : mappings-<compte Linux>.json
    dans le dossier de l'application, comme les installations existantes."""
    user = re.sub(r"[^A-Za-z0-9._-]", "_", getpass.getuser() or "user")
    return os.path.join(APP_DIR, f"mappings-{user}.json")


def ensure_mappings_file(path):
    """Crée un fichier de mappings vide s'il n'existe pas. Ne touche jamais à
    un fichier existant. Retourne True si le fichier existe à la sortie."""
    if os.path.exists(path):
        return True
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("[]\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def parse_time(text):
    """« 3:00 », « 03:00 » -> (3, 0) ; None si invalide."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", text or "")
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if h > 23 or mn > 59:
        return None
    return h, mn


def calendar_to_time(cal):
    """« *-*-* 03:00:00 » -> « 03:00 » ; None si la forme n'est pas reconnue."""
    m = re.match(r"^\*-\*-\* (\d{2}):(\d{2})(?::\d{2})?$", (cal or "").strip())
    return f"{m.group(1)}:{m.group(2)}" if m else None


class Dot(tk.Canvas):
    """Pastille de couleur dessinée (jamais un caractère ● : son rendu varie
    selon la police)."""

    def __init__(self, parent, size=12, color=GREY):
        super().__init__(parent, width=size, height=size, highlightthickness=0,
                         bd=0)
        self._oval = self.create_oval(1, 1, size - 1, size - 1, fill=color,
                                      outline=color)

    def set(self, color):
        self.itemconfigure(self._oval, fill=color, outline=color)


class SetupWizard(tk.Toplevel):
    """Fenêtre de l'assistant. `app` est l'éditeur ; `ui` son module."""

    WIDTH, HEIGHT = 780, 560

    def __init__(self, app, ui, start="welcome"):
        super().__init__(app)
        self.withdraw()
        ui.install_ui_pump(self)
        self.app, self.ui = app, ui
        self.title(_("Setup assistant — Proton Drive sync"))
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._busy = False
        self._page_ok = {}            # page -> la vérification a réussi
        # Fichier de mappings : celui des services DÉJÀ installés s'il y en a
        # un. Relancer l'assistant ne doit jamais faire basculer en silence la
        # planification ni le temps réel sur un autre fichier (l'éditeur, lui,
        # demande confirmation pour ce changement).
        self.mappings_path = (schedule_manager.read_service_mappings_path()
                              or realtime_manager.read_units_mappings_path()
                              or getattr(app, "config_path", None)
                              or default_mappings_path())
        self._build_frame()
        self._pages = {}
        for name in PAGES:
            frame = ttk.Frame(self.body, padding=(16, 12))
            getattr(self, f"_build_{name}")(frame)
            self._pages[name] = frame
        self._index = PAGES.index(START_AT.get(start, start))
        self._show()
        self._place()
        self.deiconify()
        ui._safe_grab(self)

    # ---------- cadre commun ----------

    def _build_frame(self):
        head = tk.Frame(self, bg=self.ui.PROTON_PURPLE)
        head.pack(side="top", fill="x")
        self.head_title = tk.Label(head, text="", bg=self.ui.PROTON_PURPLE,
                                   fg="white", font=("", 13, "bold"),
                                   anchor="w", padx=16, pady=8)
        self.head_title.pack(side="left", fill="x", expand=True)
        self.head_step = tk.Label(head, text="", bg=self.ui.PROTON_PURPLE,
                                  fg="white", padx=16)
        self.head_step.pack(side="right")

        nav = ttk.Frame(self, padding=(16, 8))
        nav.pack(side="bottom", fill="x")
        self.btn_cancel = ttk.Button(nav, text=_("Close"), command=self._close)
        self.btn_cancel.pack(side="left")
        self.btn_next = ttk.Button(nav, text=_("Next ›"), command=self._next)
        self.btn_next.pack(side="right")
        self.btn_back = ttk.Button(nav, text=_("‹ Back"), command=self._back)
        self.btn_back.pack(side="right", padx=(0, 6))
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")

        # Corps défilant : une page trop haute pour un petit écran défile au
        # lieu de pousser les boutons hors de la fenêtre.
        outer = ttk.Frame(self)
        outer.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(outer, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._body_win = self.canvas.create_window((0, 0), window=self.body,
                                                   anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._body_win, width=e.width))
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.bind_all(seq, self._on_wheel, add="+")

    def _on_wheel(self, event):
        try:
            if not self.winfo_exists():
                return
            w = event.widget
            if not str(w).startswith(str(self)):
                return
        except (tk.TclError, AttributeError):
            return
        step = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def _place(self):
        """Taille ET position posées ensemble, plafonnées à 90 % de l'écran,
        bornées aux deux bouts."""
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(self.WIDTH, int(sw * 0.9))
        h = min(self.HEIGHT, int(sh * 0.9))
        try:
            px, py = self.app.winfo_rootx(), self.app.winfo_rooty()
            pw, ph = self.app.winfo_width(), self.app.winfo_height()
            x, y = px + (pw - w) // 2, py + (ph - h) // 3
        except tk.TclError:
            x, y = (sw - w) // 2, (sh - h) // 3
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _wrap(self):
        return min(self.WIDTH, int(self.winfo_screenwidth() * 0.9)) - 80

    def _text(self, parent, text, muted=False, pady=(0, 8)):
        lbl = ttk.Label(parent, text=text, justify="left", wraplength=self._wrap(),
                        foreground=MUTED if muted else None)
        lbl.pack(anchor="w", fill="x", pady=pady)
        return lbl

    def _command_row(self, parent, machine):
        """Ligne « commande à copier » : la machine, un champ en lecture seule
        et un bouton Copier. Retourne la StringVar de la commande."""
        ttk.Label(parent, text=machine, font=("", 9, "bold")).pack(anchor="w")
        row = ttk.Frame(parent)
        row.pack(anchor="w", fill="x", pady=(0, 8))
        var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=var, state="readonly",
                        font=("monospace", 9))
        ent.pack(side="left", fill="x", expand=True)

        def copy():
            if var.get():
                self.clipboard_clear()
                self.clipboard_append(var.get())
        ttk.Button(row, text=_("📋 Copy"), command=copy).pack(side="left",
                                                             padx=(6, 0))
        return var

    def _status_row(self, parent):
        row = ttk.Frame(parent)
        row.pack(anchor="w", fill="x", pady=(4, 8))
        dot = Dot(row)
        dot.pack(side="left", padx=(0, 6))
        var = tk.StringVar()
        ttk.Label(row, textvariable=var, justify="left",
                  wraplength=self._wrap() - 30).pack(side="left", fill="x")
        return dot, var

    # ---------- navigation ----------

    def _page_name(self):
        return PAGES[self._index]

    def _show(self):
        for f in self._pages.values():
            f.pack_forget()
        name = self._page_name()
        self._pages[name].pack(fill="both", expand=True)
        self.canvas.yview_moveto(0)
        titles = {
            "welcome": _("Welcome"),
            "cli": _("Proton Drive CLI"),
            "login": _("Sign in to Proton"),
            "mode": _("Local only, or with a NAS"),
            "shared": _("NAS — shared folder"),
            "pairs": _("NAS — data folders"),
            "watcher": _("NAS — watcher"),
            "services": _("Schedule and real time"),
            "done": _("Ready"),
        }
        self.head_title.configure(text=titles[name])
        # Numérotation des étapes réelles (1 = CLI … 7 = services), comme la
        # liste de la page d'accueil ; ni l'accueil ni la fin ne comptent.
        steps = len(PAGES) - 2
        self.head_step.configure(
            text=_("Step {n} of {t}").format(n=self._index, t=steps)
            if 0 < self._index <= steps else "")
        enter = getattr(self, f"_enter_{name}", None)
        if enter:
            enter()
        self._refresh_nav()

    def _refresh_nav(self):
        name = self._page_name()
        self.btn_back.configure(
            state="normal" if self._index > 0 and not self._busy else "disabled")
        if name == "done":
            self.btn_next.configure(text=_("Finish"), state="normal")
            return
        self.btn_next.configure(text=_("Next ›"))
        needs_check = name in ("cli", "login", "shared", "watcher", "services")
        ok = (not needs_check) or self._page_ok.get(name, False)
        self.btn_next.configure(
            state="normal" if ok and not self._busy else "disabled")

    def _set_busy(self, busy):
        self._busy = busy
        self._refresh_nav()

    def _next(self):
        name = self._page_name()
        if name == "done":
            self._finish()
            return
        leave = getattr(self, f"_leave_{name}", None)
        if leave and not leave():
            return
        self._index = self._following(self._index)
        self._show()

    def _following(self, i):
        name = PAGES[i]
        if name == "mode" and not self.nas_var.get():
            return PAGES.index("services")
        return i + 1

    def _back(self):
        i = self._index - 1
        # Local seul : revenir des services saute les pages du NAS.
        if PAGES[self._index] == "services" and not appconfig.nas_enabled():
            i = PAGES.index("mode")
        self._index = max(0, i)
        self._show()

    def _close(self):
        try:
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        self.destroy()

    def _run(self, work, done):
        """Exécute `work()` dans un fil ; `done(result)` revient sur le fil
        principal. Aucune opération lente sur le fil de l'interface."""
        self._set_busy(True)

        def target():
            try:
                res = work()
            except Exception as e:      # jamais d'exception perdue dans un fil
                res = e

            def back():
                self._set_busy(False)
                done(res)
            self._ui(back)
        threading.Thread(target=target, daemon=True).start()

    # ---------- 0. Accueil ----------

    def _build_welcome(self, f):
        self._text(f, _(
            "This assistant prepares the backup of your folders to Proton "
            "Drive, step by step. Each step is checked before you move on."))
        self._text(f, _(
            "1. The Proton Drive CLI, which does the actual transfers.\n"
            "2. Signing in to your Proton account.\n"
            "3. Local only, or with a NAS.\n"
            "4–6. For a NAS: the shared folder, the data folders, and the "
            "watcher that runs on the NAS.\n"
            "7. The nightly pass and real time.\n"
            "At the end, the system is running and only waits for the folders "
            "you want to back up."))
        self._text(f, _(
            "You can close the assistant at any time and come back later with "
            "the “Setup assistant…” button. Everything it sets stays editable "
            "in “⚙ Configuration…”."), muted=True)

    # ---------- 1. CLI ----------

    def _build_cli(self, f):
        self._text(f, _(
            "This application does not include Proton's CLI: you download it "
            "from Proton, then show the assistant where it is."))
        ttk.Button(f, text=_("Open Proton's download page"),
                   command=lambda: webbrowser.open(CLI_DOWNLOAD_URL)).pack(
                       anchor="w", pady=(0, 10))
        ttk.Label(f, text=_("Path of the “proton-drive” binary:")).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", fill="x", pady=(2, 6))
        self.cli_var = tk.StringVar()
        self.cli_var.trace_add("write", lambda *a: self._invalidate("cli"))
        ttk.Entry(row, textvariable=self.cli_var).pack(side="left", fill="x",
                                                       expand=True)
        ttk.Button(row, text="📁", width=3, command=self._pick_cli).pack(
            side="left", padx=(6, 0))
        ttk.Button(f, text=_("Check"), command=self._check_cli).pack(anchor="w")
        self.cli_dot, self.cli_msg = self._status_row(f)

    def _enter_cli(self):
        if not self.cli_var.get():
            cur = appconfig.resolve_proton_cli()
            if appconfig.cli_is_usable(cur):
                self.cli_var.set(cur)
        if self.cli_var.get() and not self._page_ok.get("cli"):
            self._check_cli()

    def _pick_cli(self):
        p = self.ui.pick_open_file(self, title=_("Choose the proton-drive binary"),
                                   initialdir=os.path.expanduser("~"),
                                   json_only=False)
        if p:
            self.cli_var.set(p)
            self._check_cli()

    def _check_cli(self):
        path = self.cli_var.get().strip()
        self._page_ok["cli"] = False
        if not path:
            self.cli_dot.set(RED)
            self.cli_msg.set(_("Give the path of the binary first."))
            self._refresh_nav()
            return
        if not appconfig.cli_is_usable(path):
            self.cli_dot.set(RED)
            self.cli_msg.set("\n".join(appconfig.cli_unusable_explanation(path)))
            self._refresh_nav()
            return
        # N'enregistrer que si le chemin change : traverser la page sur une
        # installation existante ne doit pas transformer la résolution
        # automatique en chemin écrit en dur.
        if os.path.realpath(path) != os.path.realpath(appconfig.resolve_proton_cli()):
            appconfig.set_proton_cli_path(path)
        self.cli_dot.set(BLUE)
        self.cli_msg.set(_("Reading the CLI version…"))
        engine = getattr(self.ui, "_ENGINE", None)

        def work():
            res = engine.cli_version_status() if engine else ("unknown", None)
            # Installation neuve : partir du bon réglage plutôt que d'afficher,
            # au lancement suivant, l'avis « normalisation des extensions
            # désactivée » pour une fonction jamais utilisée. Même décision que
            # l'éditeur et le moteur (effective_rename_ext).
            try:
                if (engine and res[1] and not appconfig.rename_ext_auto_disabled()
                        and not appconfig.effective_rename_ext(
                            engine.cli_supports_shared_delete)):
                    appconfig.set_rename_ext_enabled(False)
                    appconfig.set_rename_ext_auto_disabled(True)
            except Exception:
                pass
            return res

        def done(res):
            if isinstance(res, Exception) or not res[1]:
                self.cli_dot.set(RED)
                self.cli_msg.set(_("The CLI did not report its version. Check "
                                   "that this is the Proton Drive CLI."))
            else:
                status, version = res
                tested = getattr(engine, "CLI_TESTED_VERSION", "?")
                self._page_ok["cli"] = True
                if status == "ok":
                    self.cli_dot.set(GREEN)
                    self.cli_msg.set(_("Proton Drive CLI {v} — the version this "
                                       "application was tested with.").format(
                                           v=version))
                else:
                    self.cli_dot.set(YELLOW)
                    self.cli_msg.set(_("Proton Drive CLI {v}. This application "
                                       "was tested with {t}: it works, at your "
                                       "own risk.").format(v=version, t=tested))
            self._refresh_nav()
        self._run(work, done)

    # ---------- 2. Connexion ----------

    def _build_login(self, f):
        self._text(f, _(
            "A browser window opens for you to sign in to Proton. Your password "
            "and 2FA stay in the browser — this application never sees them."))
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=(0, 6))
        ttk.Button(row, text=_("Sign in…"), command=self._login).pack(side="left")
        ttk.Button(row, text=_("Check again"), command=self._check_login).pack(
            side="left", padx=(6, 0))
        self.login_dot, self.login_msg = self._status_row(f)

    def _enter_login(self):
        if not self._page_ok.get("login"):
            self._check_login()

    def _login(self):
        box = {}

        def regrab():
            # Reprendre le grab seulement quand la fenêtre de connexion est
            # FERMÉE : tant qu'elle est ouverte, ses boutons doivent répondre.
            try:
                if box.get("dlg") is not None and box["dlg"].winfo_exists():
                    self.after(300, regrab)
                    return
            except tk.TclError:
                pass
            self.ui._safe_grab(self)

        def after_login():
            self._check_login()
            self.after(300, regrab)
        box["dlg"] = self.ui.ProtonLoginDialog(self, on_done=after_login)

    def _check_login(self):
        self._page_ok["login"] = False
        self.login_dot.set(BLUE)
        self.login_msg.set(_("Checking the Proton session…"))

        def done(ok):
            if ok is True:
                self._page_ok["login"] = True
                self.login_dot.set(GREEN)
                self.login_msg.set(_("Connected to Proton."))
                try:
                    self.app._refresh_auth_indicator()
                except Exception:
                    pass
            else:
                self.login_dot.set(YELLOW)
                self.login_msg.set(_("Not connected yet. Press “Sign in…”."))
            self._refresh_nav()
        self._run(realtime_manager.check_auth, done)

    # ---------- 3. Mode ----------

    def _build_mode(self, f):
        self.nas_var = tk.BooleanVar(value=appconfig.nas_enabled())
        ttk.Radiobutton(f, text=_("Local only"), variable=self.nas_var,
                        value=False).pack(anchor="w")
        self._text(f, _("The folders to back up are on this computer's own "
                        "disks. Nothing is installed elsewhere."), muted=True,
                   pady=(0, 10))
        ttk.Radiobutton(f, text=_("With a NAS"), variable=self.nas_var,
                        value=True).pack(anchor="w")
        self._text(f, _(
            "Some folders are on a NAS, mounted on this computer over NFS. A "
            "small watcher runs on the NAS so that changes made there are "
            "backed up too. You will need to run two commands on the NAS."),
            muted=True)

    def _leave_mode(self):
        appconfig.set_nas_enabled(bool(self.nas_var.get()))
        return True

    # ---------- 4. Dossier partagé ----------

    def _build_shared(self, f):
        self._text(f, _(
            "The NAS and this computer exchange their files through one shared "
            "folder: an NFS mount on this computer. Any exported folder works; "
            "the application keeps its files in a “proton-sync” folder inside "
            "it."))
        self._text(f, _("NFS mounts found on this computer:"), pady=(0, 2))
        self.shared_list = ttk.Frame(f)
        self.shared_list.pack(anchor="w", fill="x")
        self.shared_var = tk.StringVar(value=appconfig.nas_mount_path())
        self.shared_var.trace_add("write", lambda *a: self._invalidate("shared"))
        row = ttk.Frame(f)
        row.pack(anchor="w", fill="x", pady=(8, 4))
        ttk.Label(row, text=_("Shared folder (on this computer): ")).pack(side="left")
        ttk.Entry(row, textvariable=self.shared_var).pack(side="left", fill="x",
                                                          expand=True)
        brow = ttk.Frame(f)
        brow.pack(anchor="w")
        ttk.Button(brow, text=_("Refresh the list"),
                   command=self._fill_shared).pack(side="left")
        ttk.Button(brow, text=_("Check"), command=self._check_shared).pack(
            side="left", padx=(6, 0))
        self.shared_dot, self.shared_msg = self._status_row(f)

    def _fill_shared(self):
        for w in self.shared_list.winfo_children():
            w.destroy()
        mounts = realtime_manager.nfs_mounts()
        if not mounts:
            self._text(self.shared_list, _(
                "No NFS mount found. Mount the NAS folders on this computer "
                "first (see the installation guide), then press “Refresh the "
                "list”."), muted=True)
            return
        for m in mounts:
            ttk.Radiobutton(
                self.shared_list, variable=self.shared_var, value=m["point"],
                text=_("{p}   ← {s}:{e}").format(p=m["point"], s=m["server"],
                                                 e=m["export"]),
                command=lambda: self._invalidate("shared")).pack(anchor="w")

    def _invalidate(self, page):
        """Une valeur modifiée après sa vérification n'est plus vérifiée."""
        self._page_ok[page] = False
        try:
            self._refresh_nav()
        except (AttributeError, tk.TclError):
            pass                  # construction en cours

    def _enter_shared(self):
        self._fill_shared()
        if not self._page_ok.get("shared"):
            self.shared_dot.set(GREY)
            self.shared_msg.set(_("Choose the shared folder, then press “Check”."))

    def _check_shared(self):
        mount = self.shared_var.get().strip()
        self._page_ok["shared"] = False
        if not mount:
            self.shared_dot.set(RED)
            self.shared_msg.set(_("Choose the shared folder first."))
            self._refresh_nav()
            return
        self.shared_dot.set(BLUE)
        self.shared_msg.set(_("Checking…"))

        def work():
            if realtime_manager.nas_side_path(mount) is None:
                # Montage automatique (autofs, x-systemd.automount) : il
                # n'apparaît dans /proc/mounts qu'au premier accès.
                try:
                    os.listdir(mount)
                except OSError:
                    pass
            if realtime_manager.nas_side_path(mount) is None:
                return ("nfs", None)
            base = os.path.join(mount, "proton-sync")
            probe = os.path.join(base, ".setup-write-test")
            try:
                os.makedirs(base, exist_ok=True)
                with open(probe, "w", encoding="utf-8") as fh:
                    fh.write("ok")
                os.remove(probe)
            except OSError as e:
                return ("write", str(e))
            return ("ok", realtime_manager.nas_side_path(base))

        def done(res):
            if isinstance(res, Exception):
                res = ("write", str(res))
            kind, detail = res
            if kind == "nfs":
                self.shared_dot.set(RED)
                self.shared_msg.set(_("{p} is not on an NFS mount. The shared "
                                      "folder must be mounted from the NAS.")
                                    .format(p=mount))
            elif kind == "write":
                self.shared_dot.set(RED)
                self.shared_msg.set(_("Cannot write into {p}: {e}").format(
                    p=os.path.join(mount, "proton-sync"), e=detail))
            else:
                appconfig.set_nas_mount_path(mount)
                realtime_manager.refresh_nas_paths()
                self._page_ok["shared"] = True
                self.shared_dot.set(GREEN)
                self.shared_msg.set(_("OK. On the NAS, the application's files "
                                      "will be in {d}.").format(d=detail))
            self._refresh_nav()
        self._run(work, done)

    # ---------- 5. Correspondances ----------

    def _build_pairs(self, f):
        self._text(f, _(
            "On the NAS, these folders do not have the same path as on this "
            "computer. Each line pairs the path here with the path on the NAS; "
            "the assistant read them from the NFS mounts. Untick a pairing that "
            "is not used for the backup. Folders that have the same path on both "
            "sides do not appear: they need no line."))
        self.pairs_box = ttk.Frame(f)
        self.pairs_box.pack(anchor="w", fill="x")
        self._text(f, _("Add a line by hand (for a case the detection misses):"),
                   pady=(10, 2))
        row = ttk.Frame(f)
        row.pack(anchor="w", fill="x")
        self.pair_local = tk.StringVar()
        self.pair_nas = tk.StringVar()
        ttk.Entry(row, textvariable=self.pair_local, width=30).pack(side="left")
        ttk.Label(row, text=" ↔ ").pack(side="left")
        ttk.Entry(row, textvariable=self.pair_nas, width=30).pack(side="left")
        ttk.Button(row, text=_("Add"), command=self._add_pair).pack(
            side="left", padx=(6, 0))
        self._pair_rows = []          # [(BooleanVar, local, nas)]

    def _enter_pairs(self):
        known = {(p["local"], p["nas"]) for p in appconfig.nas_path_map()}
        shown = {(lv, nv) for _v, lv, nv in self._pair_rows}
        for p in appconfig.nas_path_map():
            if (p["local"], p["nas"]) not in shown:
                self._pair_line(p["local"], p["nas"], True)
                shown.add((p["local"], p["nas"]))
        for p in realtime_manager.suggested_pairs(appconfig.nas_mount_path()):
            if (p["local"], p["nas"]) not in shown:
                self._pair_line(p["local"], p["nas"],
                                not known or (p["local"], p["nas"]) in known)
                shown.add((p["local"], p["nas"]))
        if not self._pair_rows and not getattr(self, "_no_pair_label", None):
            self._no_pair_label = self._text(
                self.pairs_box, _("No line needed: no other NFS mount found."),
                muted=True)

    def _pair_line(self, local, nas, checked):
        var = tk.BooleanVar(value=checked)
        ttk.Checkbutton(self.pairs_box, variable=var,
                        text=f"{local}   ↔   {nas}").pack(anchor="w")
        self._pair_rows.append((var, local, nas))

    def _add_pair(self):
        loc, nas = self.pair_local.get().strip(), self.pair_nas.get().strip()
        if not loc or not nas:
            return
        if getattr(self, "_no_pair_label", None) is not None:
            self._no_pair_label.destroy()
            self._no_pair_label = None
        self._pair_line(loc, nas, True)
        self.pair_local.set("")
        self.pair_nas.set("")

    def _leave_pairs(self):
        appconfig.set_nas_path_map([{"local": lv, "nas": nv}
                                    for v, lv, nv in self._pair_rows if v.get()])
        self._invalidate("watcher")
        return True

    # ---------- 6. Watcher du NAS ----------

    def _build_watcher(self, f):
        self._text(f, _(
            "The watcher runs on the NAS as a system service. Give the NAS "
            "account it will run as: it must exist on the NAS, be able to read "
            "the folders you back up, and write into the shared folder."))
        row = ttk.Frame(f)
        row.pack(anchor="w", fill="x", pady=(0, 6))
        ttk.Label(row, text=_("NAS account: ")).pack(side="left")
        self.acct_var = tk.StringVar()
        self.acct_var.trace_add("write", lambda *a: self._invalidate("watcher"))
        ttk.Entry(row, textvariable=self.acct_var, width=20).pack(side="left")
        ttk.Button(row, text=_("Send to the NAS"), command=self._send).pack(
            side="left", padx=(8, 0))
        self.send_dot, self.send_msg = self._status_row(f)
        self.cmd_box = ttk.Frame(f)
        self.cmd_box.pack(anchor="w", fill="x")
        self._text(self.cmd_box, _(
            "Then, on the NAS, run these two commands — the first installs the "
            "only library the watcher needs, the second installs and starts the "
            "service:"))
        self.cmd_pkg = self._command_row(self.cmd_box, _("On the NAS:"))
        self.cmd_svc = self._command_row(self.cmd_box, _("On the NAS:"))
        ttk.Button(f, text=_("Check the watcher"), command=self._check_watcher).pack(
            anchor="w", pady=(4, 0))
        self.test_box = ttk.Frame(f)
        self.test_box.pack(anchor="w", fill="x", pady=(4, 0))

    def _enter_watcher(self):
        if not self.acct_var.get():
            nas_dir = realtime_manager.nas_side_path(realtime_manager.NAS_BASE) or ""
            self.acct_var.set(appconfig.nas_service_account()
                              or realtime_manager.suggested_service_account(nas_dir))
        self.cmd_pkg.set("sudo apt install python3-pyinotify")
        if not self.cmd_svc.get():
            self.send_dot.set(GREY)
            self.send_msg.set(_("Press “Send to the NAS”."))

    def _send(self):
        acct = self.acct_var.get().strip()
        self._page_ok["watcher"] = False
        if not appconfig.valid_account_name(acct):
            self.send_dot.set(RED)
            self.send_msg.set(_("“{a}” is not a valid account name: use letters, "
                                "digits, “.”, “_” or “-”, starting with a "
                                "letter.").format(a=acct))
            self._refresh_nav()
            return
        appconfig.set_nas_service_account(acct)
        realtime_manager.refresh_nas_paths()
        self.send_dot.set(BLUE)
        self.send_msg.set(_("Sending the scripts to the NAS…"))

        def done(res):
            if isinstance(res, Exception):
                res = (False, str(res), None)
            ok, msg, _cmd = res
            _text, nas_dir = realtime_manager.nas_service_plan()
            if not ok:
                self.send_dot.set(RED)
                self.send_msg.set(msg or "")
            elif not nas_dir:
                self.send_dot.set(RED)
                self.send_msg.set(_("The service file could not be built: "
                                    "the shared folder is not on an NFS mount."))
            else:
                self.send_dot.set(GREEN)
                self.send_msg.set(_("Scripts and service file are on the NAS, in "
                                    "{d}.").format(d=nas_dir))
                self.cmd_svc.set(realtime_manager.nas_service_install_command(nas_dir))
            self._refresh_nav()
        self._run(realtime_manager.push_scripts_to_nas, done)

    def _tests(self):
        """Paires à tester : le dossier partagé lui-même (preuve que le
        watcher répond), puis chaque correspondance enregistrée."""
        mount = appconfig.nas_mount_path()
        out = []
        nas_dir = realtime_manager.nas_side_path(mount)
        if nas_dir:
            out.append((_("Shared folder"), mount, nas_dir))
        for p in appconfig.nas_path_map():
            out.append((p["local"], p["local"], p["nas"]))
        return out

    def _check_watcher(self):
        for w in self.test_box.winfo_children():
            w.destroy()
        tests = self._tests()
        rows = []
        for label, _loc, _nas in tests:
            dot, var = self._status_row(self.test_box)
            dot.set(BLUE)
            var.set(_("{l}: testing…").format(l=label))
            rows.append((dot, var, label))
        # Garder les StringVar en vie : une variable ramassée par le
        # ramasse-miettes vide son étiquette.
        self._test_rows = rows
        self._page_ok["watcher"] = False
        mount = appconfig.nas_mount_path()

        def work():
            return [realtime_manager.run_selftest(loc, nas, nas_mount=mount)
                    for _l, loc, nas in tests]

        def done(res):
            if isinstance(res, Exception):
                res = [("yellow", str(res))] * len(rows)
            colors = {"green": GREEN, "yellow": YELLOW, "red": RED}
            all_green = bool(res)
            for (dot, var, label), (color, msg), (_l, loc, nas) in zip(rows, res,
                                                                       tests):
                dot.set(colors.get(color, GREY))
                var.set(_("{l}: {m}").format(l=label, m=msg))
                all_green = all_green and color == "green"
                if loc != mount:
                    try:
                        appconfig.set_selftest_verdict(loc, nas, color)
                    except Exception:
                        pass
            if res and res[0][0] == "yellow":
                self._text(self.test_box, _(
                    "No answer from the watcher. On the NAS, check that the "
                    "service started, and that the account exists: "
                    "journalctl -u proton-nas-watch.service -n 30 --no-pager"),
                    muted=True)
            self._page_ok["watcher"] = all_green
            self._refresh_nav()
        self._run(work, done)

    # ---------- 7. Planification et temps réel ----------

    def _build_services(self, f):
        self._text(f, _(
            "A full pass runs every night and catches anything the real time "
            "missed. Real time sends a change within about a minute."))
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=(0, 6))
        ttk.Label(row, text=_("Nightly pass at (HH:MM): ")).pack(side="left")
        self.time_var = tk.StringVar(value="03:00")
        ttk.Entry(row, textvariable=self.time_var, width=7).pack(side="left")
        self.delete_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, variable=self.delete_var, text=_(
            "Propagate deletions in the nightly pass")).pack(anchor="w")
        self._text(f, _("Off by default: a file deleted here stays on Proton. "
                        "You can turn it on later, once you trust your "
                        "mappings."), muted=True)
        # Temps réel : coché pour une installation neuve, sinon l'état actuel.
        fresh = not (schedule_manager.service_exists()
                     or realtime_manager.units_exist())
        self.rt_var = tk.BooleanVar(value=fresh or realtime_manager.units_exist())
        ttk.Checkbutton(f, variable=self.rt_var, text=_("Real time")).pack(anchor="w")
        self._text(f, _("Mappings file: {p}").format(p=self.mappings_path),
                   muted=True, pady=(8, 4))
        ttk.Button(f, text=_("Install"), command=self._install).pack(anchor="w")
        self.inst_dot, self.inst_msg = self._status_row(f)
        # Un réglage modifié n'est appliqué qu'en cliquant sur « Installer ».
        for var in (self.time_var, self.delete_var, self.rt_var):
            var.trace_add("write", lambda *a: self._services_changed())
        self.linger_box = ttk.Frame(f)
        self.linger_box.pack(anchor="w", fill="x")
        self.linger_dot, self.linger_msg = self._status_row(self.linger_box)
        # Commande et bouton : affichés seulement tant que le linger est
        # inactif (une fois actif, il n'y a plus rien à lancer).
        self.linger_fix = ttk.Frame(self.linger_box)
        self.linger_cmd = self._command_row(self.linger_fix, _("On this computer:"))
        ttk.Button(self.linger_fix, text=_("Check again"),
                   command=self._check_linger).pack(anchor="w")

    def _enter_services(self):
        cur = calendar_to_time(schedule_manager.read_timer_calendar())
        if cur:
            self.time_var.set(cur)
        if schedule_manager.service_exists():
            self.delete_var.set(bool(schedule_manager.read_service_delete()))
        if not self._page_ok.get("services"):
            installed = schedule_manager.read_service_mappings_path()
            if (installed and schedule_manager.service_exists()
                    and os.path.realpath(installed)
                    == os.path.realpath(self.mappings_path)):
                # Installation existante : rien à refaire pour continuer.
                self._page_ok["services"] = True
                self.inst_dot.set(GREEN)
                self.inst_msg.set(_("Already installed. “Install” rewrites them "
                                    "with the settings above."))
            else:
                self.inst_dot.set(GREY)
                self.inst_msg.set(_("Press “Install”."))
            self._refresh_nav()
        self._check_linger()

    def _services_changed(self):
        if not self._page_ok.get("services"):
            return
        self._page_ok["services"] = False
        self.inst_dot.set(GREY)
        self.inst_msg.set(_("Press “Install”."))
        self._refresh_nav()

    def _check_linger(self):
        def done(ok):
            if ok is True:
                self.linger_dot.set(GREEN)
                self.linger_msg.set(_("The services keep running when you are "
                                      "logged out (linger is on)."))
                self.linger_cmd.set("")
                self.linger_fix.pack_forget()
            else:
                self.linger_dot.set(YELLOW)
                self.linger_msg.set(_("Linger is off: the nightly pass only runs "
                                      "while you are logged in. To have it run "
                                      "anyway, run this command:"))
                self.linger_cmd.set(schedule_manager.linger_command())
                self.linger_fix.pack(anchor="w", fill="x")
        def work():
            try:
                res = schedule_manager.linger_enabled()
            except Exception:
                res = False
            self._ui(lambda: done(res))
        threading.Thread(target=work, daemon=True).start()

    def _install(self):
        t = parse_time(self.time_var.get())
        self._page_ok["services"] = False
        if t is None:
            self.inst_dot.set(RED)
            self.inst_msg.set(_("Give the time as HH:MM, for example 03:00."))
            self._refresh_nav()
            return
        cal = f"*-*-* {t[0]:02d}:{t[1]:02d}:00"
        path, delete, rt = self.mappings_path, self.delete_var.get(), self.rt_var.get()
        if rt and not self._cold_cache_ok(path):
            return
        nas = appconfig.nas_enabled()
        self.inst_dot.set(BLUE)
        self.inst_msg.set(_("Installing…"))

        def work():
            lines = []
            if not ensure_mappings_file(path):
                return False, [_("Cannot create {p}.").format(p=path)]
            ok, msg = schedule_manager.install_or_update(
                path, on_calendar=cal, delete=delete, enable=True)
            lines.append(msg)
            if not ok:
                return False, lines
            if rt:
                ok, msg, _cmd = realtime_manager.install_or_update_units(path)
                lines.append(msg)
                if not ok:
                    return False, lines
            if nas:
                ok, msg = realtime_manager.push_mappings_to_nas(path)
                if not ok:
                    lines.append(msg)
                    return False, lines
            return True, lines

        def done(res):
            if isinstance(res, Exception):
                res = (False, [str(res)])
            ok, lines = res
            self.inst_dot.set(GREEN if ok else RED)
            self.inst_msg.set("\n".join(l for l in lines if l))
            self._page_ok["services"] = ok
            self._refresh_nav()
        self._run(work, done)

    def _cold_cache_ok(self, path):
        """Même avertissement que la fenêtre temps réel : aucun mapping prêt
        pour le temps réel. Rien à juger pour un fichier vide ou absent."""
        try:
            ready, total = realtime_manager.mappings_ready_count(path)
        except Exception:
            return True
        if total == 0 or ready > 0:
            return True
        ok = self.ui.dlg_confirm(
            self,
            _("No mapping is ready for real-time yet: no full pass has analyzed the "
              "tree.\n\n"
              "Real-time only synchronizes folders whose entire tree has been "
              "analyzed; it never builds that analysis itself (it would freeze for "
              "hours on large folders). Until a full pass runs, real-time will hand "
              "every change over to the scheduled pass.\n\n"
              "Recommended: run a full pass first (⏰ Schedule, or the “Run sync” "
              "button) and let it finish, then enable real-time.\n\n"
              "Enable real-time anyway?"),
            title=_("No mapping ready for real-time"), kind="warning",
            ok_text=_("Enable anyway"), cancel_text=_("Cancel"))
        self.ui._safe_grab(self)
        return ok

    # ---------- 8. Fin ----------

    def _build_done(self, f):
        self._text(f, _(
            "The system is ready: it only waits for mappings — the folders you "
            "want to back up."))
        self._text(f, _(
            "Add a folder with “➕ Folder…” in the main window. Its first full "
            "pass (“▶ Run sync”) sends the existing files; after that, the "
            "nightly pass and real time take over."))
        self.add_now = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, variable=self.add_now, text=_(
            "Add a first folder now")).pack(anchor="w", pady=(8, 0))

    def _finish(self):
        app, path, add = self.app, self.mappings_path, self.add_now.get()
        self._close()
        try:
            if not getattr(app, "dirty", False) and os.path.exists(path) \
                    and getattr(app, "config_path", None) != path:
                app._load(path)
            if add:
                app.after(200, app.on_add_folder)
        except Exception:
            pass


def open_wizard(app, ui, start="welcome"):
    """Ouvre l'assistant (une seule fenêtre à la fois)."""
    cur = getattr(app, "_setup_wizard", None)
    try:
        if cur is not None and cur.winfo_exists():
            cur.lift()
            return cur
    except tk.TclError:
        pass
    app._setup_wizard = SetupWizard(app, ui, start=start)
    return app._setup_wizard
