# Security

This is community software, not affiliated with or endorsed by Proton AG. It runs Proton's official `proton-drive` CLI and never handles your Proton password.

## Reporting a problem

- A vulnerability (for example a way to make the tool upload, trash or expose files it should not): use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability"). Do not open a public issue for it.
- Any other bug: open an issue and attach `proton-drive-sync-doctor --redact`.

## Never post un-redacted output

`proton-drive-sync-doctor` without `--redact` contains your home path, folder names, mapping paths and possibly account details. Always run it with `--redact`, then read the result before you paste it. Also check logs and mappings files for personal paths and e-mail addresses before sharing them.

Problems in Proton's CLI or in Proton Drive itself belong to Proton, not to this project.
