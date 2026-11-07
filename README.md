# abacusai-transcript-credit-analysis

> See exactly where your Abacus.AI credits went. `credit-scanner` reads the project transcripts you have saved as text files and reports credits and USD cost per project, per step, with totals and statistics.

`credit-scanner` is a single, dependency-light bash script. Point it at a folder of `*-abacusai-transcript.txt` files and it prints a summary table (file size, total credits, USD value), a TOTAL row and mean/median/mode statistics. `--dive` breaks each transcript down step by step, and `--csv` exports everything for a spreadsheet.

<table><tr>
<td><img src=".github/donate-bitcoin-qr.png" width="96" alt="Bitcoin donation QR code"></td>
<td><sub>💛 If you find this project useful, I'd be grateful for any donation. Thank you!<br>
<b>Bitcoin:</b> <code>bc1qu6dkcchurnutgc40y6n53s3zm588z9nnkm2ygq</code></sub></td>
</tr></table>

## 🚀 One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash
```

Installs `credit-scanner` to `~/.local/bin` and runs its built-in self-test before reporting success. Or run it once without installing anything:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/credit-scanner.sh)
```

More choices are in [Installation](#installation).

---

## Table of Contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Option 1: one-line installer](#option-1-one-line-installer)
  - [Option 2: run without installing](#option-2-run-without-installing)
  - [Option 3: git clone](#option-3-git-clone)
  - [Option 4: Nix / NixOS](#option-4-nix--nixos)
  - [Uninstall](#uninstall)
- [Usage](#usage)
- [Options](#options)
- [Sample output](#sample-output)
- [How credits are detected](#how-credits-are-detected)
- [Development and tests](#development-and-tests)
- [Troubleshooting / FAQ](#troubleshooting--faq)
- [Changelog](#changelog)
- [License](#license)

---

## What it does

- **Summary table**: one row per transcript with file size, total credits and USD value, plus a **TOTAL** row.
- **Statistics**: mean, median and mode credits (and USD) across all transcripts.
- **Dive-in mode** (`-d`): each transcript split into steps. Every row is labelled with the prompt and the file or artifact it touched (for example `[README.md] Clickable table of contents...`), followed by credits and USD for that step and the **PROJECT TOTALS**.
- **Word counts** (`-w`): how much text went into each step or transcript.
- **CSV export** (`-c`): summary or dive data ready for a spreadsheet.
- **Sorting** (`-s`): by filename, credits, size or date. **Top N** (`-n`) for the most expensive projects.
- **Custom price** (`--rate`): the default is **$10 per 10,000 credits** ($0.001 per credit).
- Safe with awkward filenames (spaces, `:` and quotes). Skips hidden files, `*.csv` exports, binary files and the scanner itself.

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Requirements

| Requirement | Notes |
|---|---|
| **bash 4.0+** | Default on Linux and NixOS. macOS ships bash 3.2, so run `brew install bash` there. |
| **awk** | Any POSIX awk. Tested with gawk, mawk, BWK/one-true-awk (BSD/macOS) and busybox awk. |
| **coreutils** | `sort`, `wc`, `date`, `mktemp`, plus `grep`. These are already on every normal system. |
| **curl or wget** | Only needed for the one-line installer and run-from-curl. |

Run `credit-scanner --self-test` at any time to check that everything works on your machine.

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Installation

### Option 1: one-line installer

```bash
# Per-user install to ~/.local/bin (no sudo)
curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash

# System-wide install to /usr/local/bin (uses sudo only if needed)
curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash -s -- --system

# Custom location
curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash -s -- --prefix "$HOME/opt"
```

The installer goes beyond "the file exists". It:

1. Checks the runtime requirements: `bash` 4+ on `PATH`, a working POSIX `awk`, `sort`, `wc`, `grep`, `date` and `mktemp`.
2. Downloads the script, then checks its shebang and version marker and runs `bash -n` on it.
3. Runs the script's `--self-test` (summary, dive and CSV checks on a sample transcript) **before** installing anything.
4. Installs the script atomically, then runs `--version` and `--self-test` **again on the installed command**, through its own shebang.
5. Warns you, with the exact fix, if the install directory is not on your `PATH`.

Installer options: `--prefix DIR`, `--bin-dir DIR`, `--system`, `--name NAME`, `--ref BRANCH_OR_TAG`, `--from FILE`, `--uninstall`, `--help`.

<sub>[↑ Back to contents](#table-of-contents)</sub>

### Option 2: run without installing

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/credit-scanner.sh)
```

Add options at the end as usual:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/credit-scanner.sh) --dive ~/Documents/abacus-ai
```

<sub>[↑ Back to contents](#table-of-contents)</sub>

### Option 3: git clone

```bash
git clone https://github.com/entropytwo-ai/abacusai-transcript-credit-analysis.git
cd abacusai-transcript-credit-analysis
./credit-scanner.sh --help        # run in place
make install                      # or install to ~/.local/bin (PREFIX=/usr/local for system-wide)
```

`make install` uses the same verifying installer as Option 1, with your local copy.

<sub>[↑ Back to contents](#table-of-contents)</sub>

### Option 4: Nix / NixOS

The script uses `#!/usr/bin/env bash`, so it runs as-is on NixOS. Option 1 works there too.

`~/.local/bin` is **not** on `PATH` by default on NixOS. Add it with home-manager (`home.sessionPath = [ "$HOME/.local/bin" ];`) or in `~/.bashrc` (`export PATH="$HOME/.local/bin:$PATH"`).

A `flake.nix` is included:

```bash
nix run github:entropytwo-ai/abacusai-transcript-credit-analysis -- --help     # run without installing
nix profile install github:entropytwo-ai/abacusai-transcript-credit-analysis   # install into your profile
nix develop                                                                     # dev shell: shellcheck, gawk, mawk, busybox
```

You can also add it to a NixOS or home-manager config: add the flake as an input and put `inputs.credit-scanner.packages.${pkgs.system}.default` in `environment.systemPackages` or `home.packages`.

<sub>[↑ Back to contents](#table-of-contents)</sub>

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/entropytwo-ai/abacusai-transcript-credit-analysis/main/install.sh | bash -s -- --uninstall
# system-wide install:  ... | bash -s -- --uninstall --system
# from a clone:         make uninstall
```

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Usage

```text
credit-scanner [OPTIONS] [FILE|DIR ...]
```

With no arguments, it scans the **current directory**. You can pass any mix of files and directories. Directories are scanned non-recursively. Files you name explicitly are always used, even if they are hidden.

```bash
credit-scanner                                    # summary of the current directory
credit-scanner ~/Documents/abacus-ai              # summary of another directory
credit-scanner -s credits-desc -n 5               # five most expensive projects
credit-scanner -d raid-pricer-project-abacusai-transcript.txt   # step-by-step breakdown
credit-scanner -dw                                # dive-in with word counts
credit-scanner -c > credits.csv                   # spreadsheet export
credit-scanner -cd > steps.csv                    # per-step spreadsheet export
credit-scanner -p '*-abacusai-transcript.txt'     # only matching files
credit-scanner --rate 12.5                        # $12.50 per 10,000 credits
```

Exit status: `0` success, `1` no transcript files found, `2` usage error.

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Options

| Option | Description |
|---|---|
| `-d`, `--dive` | Per-transcript breakdown: one row per step/topic with credits and USD. |
| `-w`, `--words` | Add word counts (summary and dive). |
| `-c`, `--csv` | CSV output instead of tables. |
| `-s`, `--sort KEY` | `filename` (default), `credits-desc`, `credits-asc`, `size`, `size-asc`, `date`, `date-desc`. Aliases: `name`, `credits`. |
| `-n`, `--top N` | List only the first N transcripts after sorting. TOTAL and statistics still cover all files. |
| `-r`, `--rate USD` | Price per 10,000 credits (default `10`). |
| `-p`, `--pattern GLOB` | Filename glob used when scanning directories (default `*`). |
| `-D`, `--dir DIR` | Directory to scan (same as passing `DIR`). |
| `--color WHEN` / `--no-color` | Bold headings: `auto` (default, terminals only), `always`, `never`. `NO_COLOR` is honored. |
| `--self-test` | Check dependencies and run a built-in sanity test. |
| `-V`, `--version` | Print version. |
| `-h`, `--help` | Show help. |

You can combine short flags (`-dw`, `-cs credits-desc`), attach values (`-n5`, `-scredits`) and write long options as `--sort=size`.

`date` sorting uses a `YYYY-MM-DD` date in the filename if there is one, and the file modification time otherwise.

Set `CREDIT_SCANNER_AWK` to force a particular awk, for example `CREDIT_SCANNER_AWK=mawk` or `CREDIT_SCANNER_AWK="busybox awk"`.

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Sample output

From the bundled test fixtures, as staged by `make test` (`credit-scanner tests/fixtures`; one filename contains `:` on purpose):

```text
======================================================================================================
Filename (No Extension)                               :  File Size :   Total Credits :    USD Value
======================================================================================================
------------------------------------------------------:------------:-----------------:-------------
barcode-splitter: invoice-project-abacusai-transcript :      186 B :           6,220 : $      6.22
notes-without-credits                                 :       33 B :               0 : $      0.00
raid-pricer-project-abacusai-transcript               :      310 B :          15,000 : $     15.00
xtree project-abacusai-transcript                     :       90 B :       1,234,567 : $   1234.57
======================================================================================================
TOTAL                                                 :      619 B :       1,255,787 : $   1255.79
======================================================================================================

STATISTICAL SUMMARY (Valuation: $10 per 10,000 credits):
  Mean               : Credits:      313,946.75 : USD: $    313.95
  Median             : Credits:       10,610.00 : USD: $     10.61
  Mode               : Credits:               0 : USD: $      0.00
======================================================================================================
```

Dive-in mode (`credit-scanner -d tests/fixtures`, first transcript):

```text
========================================================================================================
 DIVE-IN ANALYSIS: barcode-splitter: invoice-project-abacusai-transcript (186 B)
========================================================================================================
Topic Summary                                 :    Credit Value :    USD Value
----------------------------------------------:-----------------:-------------
[screenshot.png] Create the exe file. Make... :           1,290 : $      1.29
[barcode_split...] Virustotal had 3 securi... :           4,930 : $      4.93
----------------------------------------------:-----------------:-------------
PROJECT TOTALS                                :           6,220 : $      6.22
========================================================================================================
```

CSV (`credit-scanner -c -s credits-desc tests/fixtures`):

```text
FilenameNoExt,FileSizeBytes,FileSizeHuman,TotalCredits,USDValue
"xtree project-abacusai-transcript",90,"90 B",1234567,1234.57
"raid-pricer-project-abacusai-transcript",310,"310 B",15000,15.00
"barcode-splitter: invoice-project-abacusai-transcript",186,"186 B",6220,6.22
"notes-without-credits",33,"33 B",0,0.00
"TOTAL",619,"619 B",1255787,1255.79
```

<sub>[↑ Back to contents](#table-of-contents)</sub>

## How credits are detected

- Every line containing `Credits:` followed by a number (for example `Credits: 1,653` or `Credits: ~502`) adds that number to the transcript total.
- Only the number right after the label counts. `Credits: 1,653 (about $1.65)` gives 1,653, not 1,653,165.
- In dive mode, each `Credits:` line closes a step. The step is labelled from the text before it: the first real prompt line, plus the nearest file or artifact name in brackets. UI noise such as `Copy`, `Thought for 12s` or code-fence markers is ignored.
- USD = credits × rate ÷ 10,000. Totals are computed from exact credits, not from rounded row values.
- Mode is the most frequent per-transcript total. If several values tie, the smallest one is shown.

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Development and tests

```bash
make lint     # shellcheck credit-scanner.sh install.sh tests/run-tests.sh
make test     # full test suite
make check    # both
```

`tests/run-tests.sh` runs the scanner against the sample transcripts in `tests/fixtures/`, including filenames with spaces and `:`, plus a hidden file, a CSV export, a binary file and a fake `credit-scanner.sh` that must all be skipped. Every check runs once per awk found on the machine (awk, gawk, mawk, original-awk/nawk, busybox awk) and covers:

- Summary, dive, dive+words and both CSV outputs compared against golden files in `tests/expected/`.
- No `\1,\2` artifacts in dive output, and totals above 2³¹ do not overflow.
- Every sort key, `--top`, `--rate`, `--pattern`, multiple file arguments and scanning the current directory.
- Error handling and exit codes.
- The installer: verified install, a working installed command, uninstall, and rejection of a broken script.

A GitHub Actions workflow is included as [`ci/github-actions-ci.yml`](ci/github-actions-ci.yml). It runs shellcheck plus the tests on Linux (gawk, mawk, BWK awk, busybox) and on macOS (BSD userland). To turn it on, move it to `.github/workflows/ci.yml`. It is stored outside that folder because the automation that published this repo is not allowed to create workflow files:

```bash
mkdir -p .github/workflows && git mv ci/github-actions-ci.yml .github/workflows/ci.yml && git commit -m "Enable CI" && git push
```

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Troubleshooting / FAQ

**`bash 4.0 or newer is required`.** You are on macOS's bash 3.2. Run `brew install bash` and then `bash credit-scanner.sh`, or reinstall, because the installed command uses `#!/usr/bin/env bash` and will pick up Homebrew's bash.

**`credit-scanner: command not found` after installing.** `~/.local/bin` is not on your `PATH`. The installer prints the exact line to add. On NixOS, see [Option 4](#option-4-nix--nixos).

**A file I expected is missing from the table.** Hidden files, `*.csv`, binary files and files named `credit-scanner`/`credit-scanner.sh` are skipped when scanning a directory. Pass the file explicitly to include it anyway.

**Some rows show `0` credits.** That file has no `Credits: N` lines, for example a notes file. Use `-p '*-abacusai-transcript.txt'` to scan only transcripts.

**The old version printed `\1,\2` in dive mode.** That came from regex back-references that mawk and busybox awk do not support. Number formatting is now done portably and the test suite checks for it with every awk.

<sub>[↑ Back to contents](#table-of-contents)</sub>

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

<sub>[↑ Back to contents](#table-of-contents)</sub>

## License

Copyright (C) 2026 Andrew Graham (entropytwo-ai).

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License v3.0** or (at your option) any later version. See [LICENSE](LICENSE) for the full text.

<sub>[↑ Back to contents](#table-of-contents)</sub>
