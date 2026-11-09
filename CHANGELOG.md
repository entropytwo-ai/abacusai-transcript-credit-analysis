# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- A **Calendar** view (new header link between **Dive-in** and **Projects**) showing **credit and $ usage per day, broken down by project**. Each day cell lists its projects with a colored dot, the day's per-project credit count and dollar value, plus a day total; a summary shows total credits and dollars for the selected span. Dollars are valued **as incurred** (each day at the cost per 10,000 credits in effect that day, matching the valuation band). Every project line is a **clickable link to its dive-in page**. Dates use the display timezone.
  - **Five views** via a tab switcher: **Month** (default, opens on the latest month with data), **Week** (Sunday-first, snaps to the week of the latest usage), **Year** (twelve mini-months with per-day credit numbers), **Range** (pick a start and end date), and **Schedule** (a chronological agenda listing every day that had usage or a cost change). Each view has its own **Prev/Next** navigation limited to the recorded range.
  - **Cost-change tracking**: when the **cost per 10,000 credits** changes, the day it takes effect is flagged on the calendar with an up/down badge showing the old → new price and the percent change, and a **summary strip** lists all cost changes in the selected span. Both **applied** changes (from the recorded price history) and **scheduled future** changes (pre-announced in Settings) are shown, so a price rise is visible on the calendar before and after it lands.
- **Schedule a future cost change** in **Settings**: pre-announce a price rise (or drop) with its effective date and an optional note, the way providers notify customers ahead of time. It appears on the cost chart as a **dashed projection** climbing toward the new price, and switches on by itself on the effective date — recorded into the price history and made the live cost automatically, with no action needed on the day. Pending changes can be removed before they take effect.
- A compact **Credit valuation** band just under the top cards that puts a dollar figure on inflation without disturbing the layout. It shows the total valued **at today's rate**, the same credits valued **as incurred** (each turn priced at the cost per 10,000 credits that was in effect on the day it happened — a blended, dollar-cost-average style figure), the **blended rate** behind that figure, and the **inflation delta** between the two. Until a second price is recorded in **Settings** the as-incurred total equals today's total and the delta is `$0.00`; the blend and the delta start to move on their own as prices rise over time. A **Show per-project delta** toggle reveals two extra table columns — each project's **USD (as incurred)** and its **Δ vs today** — that stay hidden by default so the table keeps its current width.
- An **A Word From Douglas Adams** link in the header (next to the brand) and the footer that plays the video in an **in-window popup** (a modal overlay with an embedded player, a close button, backdrop-click and `Esc` to dismiss) instead of leaving the page. Falls back to a normal link if JavaScript is unavailable.
- A **Cost per 10,000 credits over time** chart at the bottom of the dashboard that tracks credit inflation. Because Abacus.AI does not publish a live price for credits, the chart can't update on its own; instead it records a new dated point automatically whenever the owner changes the cost in **Settings**, so the line builds up the inflation curve as prices rise over time. The line **slopes** between recorded changes (hills when the cost rises, valleys when it falls) and holds flat to today, and the **current price rides the line** — a marker and a number sit on the line at "now" and move up or down as new slopes form. A baseline point is seeded from the current cost on first run, and the current cost plus the percentage increase since the first recorded point are shown above the chart.
- A **GitHub repo link** (small GitHub-mark icon) next to each project name on the summary dashboard, the all-projects dive-in, and each single project page. Repo URLs are editable from the Projects admin page (new **GitHub repo URL** field) and are stored per project in the database, which stays out of GitHub like the rest of your data.
- An **Active times per day** chart on the dashboard and on each project dive-in: one dot per turn placed by the time of day you prompted (in the display timezone), with later-in-the-day times higher, hour marks every three hours, horizontal gridlines and vertical day separators.
- **Time Spent** (agent run time) per project as a dashboard column, and **Turns** plus **Time Spent** added to the statistical summary, with a short explanation of Turns, Time Spent and Words (including a Moby-Dick scale reference for word counts).
- The dive-in now shows the **turn time** (`HH:MM`, display timezone) next to each date.
- PDF exports for the dashboard (`/export/summary.pdf`) and the dive-in view (`/export/dive.pdf`), with **Download PDF** / **Download dive PDF** buttons next to the CSV ones. Built with `fpdf2` (pure Python, no system libraries) so a fresh install keeps working.

### Changed
- Dates are now shown in a **display timezone** (default `America/New_York`) instead of UTC, including the **Last synced** time, with the timezone shown in the column headings (e.g. `EST`/`EDT`).
- The dive-in moves **project totals to the top** of each project; the per-project header sticks while you scroll and is replaced by the next project's header.
- The summary shows agent run time as **`H M`** (e.g. `4h 9m`) instead of a decimal number of hours.
- The summary table's **TOTAL** row now sits at the top of the data (just under the column headings) instead of the bottom, and the summary PDF matches.

### Fixed
- Dynamic responses are now sent with `no-store`, so the CDN in front of the always-on site can't cache and drop the login cookie.

### Internal
- Moved the CI workflow to `.github/workflows/github-actions-ci.yml` so GitHub Actions runs it.

## [Web 1.0.0] - 2026-11-07

### Added
- `web/`: a private web dashboard (FastAPI + SQLite) that builds the credit-scanner report straight from the Abacus.AI API, with no copy and paste.
- Summary with Created / Last activity / Chats / Turns columns, TOTAL row, Total/Mean/Median/Mode statistics with the token-scope note, and a credits-per-day chart.
- Per-project and all-project dive-in pages with two-line, PII-scrubbed **You:** / **Agent:** excerpts, plus agent run time per turn.
- Automatic grouping of split chats, plus a Projects page to move, exclude, rename or merge.
- Daily sync and a **Sync now** button. Incremental: only changed chats are downloaded and only new turns get excerpts.
- Owner and viewer accounts for sharing, one-time setup link, CSV exports, `run.sh` installer with verification, and an offline pytest suite.

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
