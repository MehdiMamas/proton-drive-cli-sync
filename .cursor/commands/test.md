# /test [pytest args]

Run the test suite in WSL and report the result.

- Command (PowerShell): `wsl -- bash scripts/test.sh <args>`. Examples: `/test`, `/test -k equal_size -vv`.
- If `scripts/test.sh` does not exist yet, phase 1 has not been merged: say so and stop.
- Report: the pytest summary line, and for each failure the test name, the assertion, and the most likely cause
  in the code under test (file:line). Do not change code unless asked.
