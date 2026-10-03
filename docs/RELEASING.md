# Releasing

Steps marked **[human]** are not done by the coding agent. The agent never pushes tags, never pushes to the AUR and never runs `makepkg`.

1. Update `VERSION` and `CHANGELOG.md` (`## [X.Y.Z] - date`). Merge to `main`.
2. **[human]** Tag: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
3. **[human]** Build in a clean Arch environment (container, or `extra-x86_64-build` from `devtools`):

   ```bash
   cd packaging/arch
   extra-x86_64-build        # runs check(): the test suite, no network, temporary HOME
   ```

4. **[human]** Lint the package: `namcap PKGBUILD` and `namcap *.pkg.tar.zst`.
5. **[human]** Verify the generated units with systemd. Create a mapping whose folder contains a space, a quote and a `%`, schedule it in the GUI, then:

   ```bash
   systemd-analyze --user verify ~/.config/systemd/user/proton-sync.service
   systemctl --user cat proton-sync.service   # ExecStart=/usr/bin/proton-drive-sync, quoted paths
   ```

6. **[human]** Install on a test machine (`makepkg -si`) and run `proton-drive-sync-doctor --redact`.
7. **[human]** Update the AUR repository: copy `PKGBUILD` and `proton-drive-cli-sync-git.install`, run `makepkg --printsrcinfo > .SRCINFO`, commit and push to `ssh://aur@aur.archlinux.org/proton-drive-cli-sync-git.git`.
8. **[human]** Announce, with the disclaimer: community software, not affiliated with Proton AG, use at your own risk.
