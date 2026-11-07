# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-07

### Added
- **Words** and **Est. Tokens** columns in every output: summary table, dive table, summary CSV (`WordCount,EstTokens`) and dive CSV.
- `-t`, `--tokens-per-word N` sets the token estimate ratio (default `1.33`, about 0.75 words per token).
- The statistical summary is now a table: a **Total** row plus Mean / Median / Mode for credits, USD, words and estimated tokens. It ends with a note that words and tokens cover only the chat transcript text, not the background agent work behind the credits.
- Dive mode adds a `(text after last Credits line)` row (or `(no Credits lines found)`), so the Words column adds up to PROJECT TOTALS.
- `words` / `words-asc` sort keys (aliases `tokens` / `tokens-asc`).

### Changed
- `-w`/`--words` is now accepted and ignored, because word counts are always shown.
- CSV layouts gained `WordCount` and `EstTokens` columns before the credit columns. Update any spreadsheet imports that use column positions.

## [1.1.0] - 2026-11-07

### Changed
- Dive-mode labels now use the prompt you typed for each turn. The scanner recognises the real Abacus.AI transcript layout (initials, prompt, timestamp, `Abacus AI Agent`, ..., `Credits:`). Before, rows were often labelled `[AG] ...`, `Abacus AI Agent`, `[logout] ...` or `[Running] ...` from the agent's own output. Other text still uses the old heuristic.
- Attachment names that contain spaces (`image (1).png`) are shown in brackets.

### Fixed
- Long labels could be cut in the middle of a multi-byte UTF-8 character, and non-ASCII text knocked the table columns out of line.

### Added
- Test fixture in the real transcript format (`tests/fixtures-real/`) with golden table and CSV output.

## [1.0.0] - 2026-11-07

First packaged release. Based on the original single-file `credit-scanner.sh`.

### Added
- One-line installer (`install.sh`) for `~/.local/bin`, `/usr/local/bin` (`--system`) or any `--prefix`/`--bin-dir`, with `--uninstall`. It checks runtime requirements and runs the self-test before and after installing.
- Run-from-curl support: `bash <(curl -fsSL .../credit-scanner.sh)`.
- `--self-test`, `--version`, `--top N`, `--rate USD`, `--pattern GLOB`, `--dir DIR`, `--color`/`--no-color`, plus `size-asc` and `date-desc` sort keys.
- Combined short flags (`-dw`) and `--opt=value` syntax.
- Multiple FILE/DIR arguments, with directory scanning.
- `--words` now also works in the summary table and summary CSV.
- `CREDIT_SCANNER_AWK` to choose a specific awk implementation.
- Makefile (`install`, `uninstall`, `test`, `lint`, `check`), `flake.nix`, test suite with fixtures and golden files, and GitHub Actions CI (Linux and macOS).

### Fixed
- Dive mode printed literal `\1,\2` instead of numbers with mawk/busybox awk. Thousands separators are now built portably, without regex back-references.
- Filenames containing `:` broke the colon-delimited records. Records now use the ASCII unit separator.
- Totals above 2,147,483,647 credits could overflow with mawk (`%d`). Totals are now printed with `%.0f`.
- `Credits: 1,653 (about $1.65)` was read as 1,653,165. Only the number after the label is used now.
- Date sort failed on months and days `08`/`09` (bash octal parsing).
- Number formatting no longer depends on the locale (`printf "%'d"`), so commas always show.
- No more need for the `sed` clean-up of non-breaking spaces and `\vert{}` after pasting.

### Changed
- Hidden files, `*.csv`, binary files and the scanner itself are skipped robustly. Empty or missing directories give a clear message and exit status 1. Usage errors exit with status 2.
- The CSV TOTAL row now uses plain numbers instead of quoted ones.
