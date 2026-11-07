#!/usr/bin/env bash
# credit-scanner.sh - Analyze Abacus.AI credit usage in saved transcript files.
#
# https://github.com/entropytwo-ai/abacusai-transcript-credit-analysis
#
# Copyright (C) 2026 Andrew Graham (entropytwo-ai)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "credit-scanner: error: bash 4.0 or newer is required (found ${BASH_VERSION:-unknown})." >&2
    echo "  macOS: 'brew install bash', then run: bash credit-scanner.sh" >&2
    exit 2
fi

set -euo pipefail

readonly VERSION="1.2.0"
readonly PROG="credit-scanner"
readonly REPO_URL="https://github.com/entropytwo-ai/abacusai-transcript-credit-analysis"
# Set CREDIT_SCANNER_AWK to force a specific awk (gawk, mawk, "busybox awk", ...).
read -ra AWK_CMD <<< "${CREDIT_SCANNER_AWK:-awk}"
((${#AWK_CMD[@]})) || AWK_CMD=(awk)
AWK_BIN="${AWK_CMD[*]}"
US=$'\x1f'   # ASCII unit separator: safe record delimiter (filenames may contain ':' or spaces)

# ---------------------------------------------------------------------------
# Shared awk helpers (POSIX awk only: works with gawk, mawk, BWK/BSD awk, busybox)
# ---------------------------------------------------------------------------
# shellcheck disable=SC2016
readonly AWK_LIB='
# cn(n, d): format number n with d decimals and thousands separators (portable,
# no regex back-references, no locale dependence, no 32-bit %d overflow).
function cn(n, d,    s, neg, ip, fp, p, out) {
    s = sprintf("%." d "f", n)
    neg = ""
    if (substr(s, 1, 1) == "-") { neg = "-"; s = substr(s, 2) }
    ip = s; fp = ""
    p = index(s, ".")
    if (p > 0) { ip = substr(s, 1, p - 1); fp = substr(s, p) }
    out = ""
    while (length(ip) > 3) {
        out = "," substr(ip, length(ip) - 2) out
        ip = substr(ip, 1, length(ip) - 3)
    }
    return neg ip out fp
}
# hs(bytes): human readable size
function hs(b) {
    if (b >= 1048576) return sprintf("%.2f MB", b / 1048576)
    if (b >= 1024)    return sprintf("%.1f KB", b / 1024)
    return sprintf("%d B", b)
}
'

# Per-file analyzer. mode=sum prints one tab-separated summary line;
# mode=dive prints the per-step breakdown (table or CSV).
# shellcheck disable=SC2016
readonly AWK_FILE='
function cln(s) { gsub(/\r/, "", s); sub(/^[ \t#*>-]+/, "", s); sub(/[ \t]+$/, "", s); return s }
function is_n(s,    l) {
    if (s == "") return 1
    if (index(s, "```") == 1) return 1
    l = tolower(s)
    if (l == "code" || l == "copy" || l == "edit" || l == "bash" || l == "python" || l == "html") return 1
    if (l == "css" || l == "json" || l == "sh" || l == "diff" || l == "output" || l == "text") return 1
    if (l ~ /^[0-9]+[ \t]*(ms|s|m|sec|mins|tokens)$/) return 1
    if (l ~ /^(thought for|thinking|generating|searching|finished)/) return 1
    return 0
}
# is_a: looks like an artifact / file name / tool label
function is_a(s) {
    if (s ~ /^Browsing /) return 1
    if (s !~ / /) {
        if (match(s, /\.[a-zA-Z0-9]+$/) && RLENGTH >= 2 && RLENGTH <= 6) return 1
        if (s ~ /^[a-zA-Z0-9_-]+$/ && length(s) < 28) return 1
    }
    return 0
}
# credit value on a "Credits: 1,653" line (only the number right after the label)
function credit_val(line,    v) {
    v = line
    sub(/.*Credits:[ \t]*~?[ \t]*/, "", v)
    if (!match(v, /^[0-9][0-9,]*/)) return 0
    v = substr(v, 1, RLENGTH)
    gsub(/,/, "", v)
    return v + 0
}
BEGIN {
    qfn = fn; gsub(/"/, "\"\"", qfn)
    mc = (cm == 1) ? 60 : 42
    lc = 0; bw = 0; tfw = 0; fc = 0
}
/Credits:[ \t]*~?[ \t]*[0-9]/ {
    v = credit_val($0)
    fc += v; nsteps++
    if (mode == "dive") {
        ctx = user_prompt()
        if (ctx == "") ctx = heuristic_ctx()
        gsub(/[ \t]+/, " ", ctx)
        ctx = clip(ctx, mc)
        u = v * rate
        if (cm == 1) {
            gsub(/"/, "\"\"", ctx)
            printf "\"%s\",%d,\"%s\",%.0f,%.0f,%.0f,%.2f\n", qfn, szb, ctx, bw, tk(bw), v, u
        } else {
            drow(ctx, bw, v, u)
        }
    }
    split("", b); lc = 0; bw = 0
    next
}
{
    c = cln($0)
    if (c != "") {
        nw = split(c, wa, /[ \t]+/)
        bw += nw; tfw += nw
        if (mode == "dive") { lc++; b[lc] = c }
    }
}
END {
    if (mode == "sum") {
        printf "%.0f\t%.0f\t%.0f\t%.2f\t%s\t%s\t%s\t%s\n", fc, tfw, tk(tfw), fc * rate, hs(szb), cn(fc, 0), cn(tfw, 0), cn(tk(tfw), 0)
    } else {
        # words after the last "Credits:" line (or in a file without any) get their own row,
        # so the Words column adds up to PROJECT TOTALS
        if (bw > 0) {
            ctx = (nsteps > 0) ? "(text after last Credits line)" : "(no Credits lines found)"
            if (cm == 1) printf "\"%s\",%d,\"%s\",%.0f,%.0f,0,0.00\n", qfn, szb, ctx, bw, tk(bw)
            else drow(ctx, bw, 0, 0)
        }
        if (cm != 1) {
            print "-------------------------------------------:------------:-------------:-----------------:-------------"
            printf "%s%-42s : %10s : %11s : %15s : $%10.2f%s\n", B, "PROJECT TOTALS", cn(tfw, 0), cn(tk(tfw), 0), cn(fc, 0), fc * rate, R
        }
    }
}
'

# Shared awk helpers for dive-mode topic detection.
# shellcheck disable=SC2016
readonly AWK_TOPIC='
# estimated tokens for a word count (tpw = tokens per word)
function tk(w) { return int(w * tpw + 0.5) }
function drow(ctx, w, v, u) {
    printf "%s : %10s : %11s : %15s : $%10.2f\n", pad(ctx, 42), cn(w, 0), cn(tk(w), 0), cn(v, 0), u
}
function is_ts(s) { return s ~ /^[0-9][0-9]?:[0-9][0-9]([ \t]*[AaPp][Mm])?$/ }
function is_agent(s) { return s ~ /^Abacus AI Agent$/ }
# Byte-safe (LC_ALL=C) UTF-8 helpers: display width counts lead bytes only.
function dw(s) { gsub(/[\200-\277]/, "", s); return length(s) }
function clip(s, w,    n) {
    if (dw(s) <= w) return s
    n = w - 3
    while (dw(substr(s, 1, n)) > w - 3) n--
    s = substr(s, 1, n)
    sub(/[\300-\377][\200-\277]*$/, "", s)
    return s "..."
}
function pad(s, w,    n) { for (n = dw(s); n < w; n++) s = s " "; return s }
# attachment chip: a single file name (may contain spaces), e.g. "image (1).png"
function is_att(s) { return is_a(s) || (length(s) < 48 && s ~ /^[^ ].*\.[A-Za-z0-9][A-Za-z0-9]?[A-Za-z0-9]?[A-Za-z0-9]?$/ && s !~ /[.?!:]  *[A-Za-z]/) }
function is_init(s) { return s ~ /^[A-Z][A-Z]?[A-Z]?$/ }
# Real Abacus.AI transcript layout for one turn:
#   <user initials> / [attachments] / <prompt lines> / <time, e.g. 4:24 PM> /
#   Abacus AI Agent / ...agent work... / Credits: N
# Returns the user prompt of the last turn in the buffer, or "" if the
# layout is not found (callers then fall back to the generic heuristic).
function user_prompt(    i, j, t, s, e, out, att, c) {
    t = 0
    for (i = lc; i >= 2; i--) {
        if (!is_ts(b[i])) continue
        for (j = i + 1; j <= lc && is_n(b[j]); j++) ;
        if (j <= lc && is_agent(b[j])) { t = i; break }
    }
    if (!t) return ""
    s = 1
    for (i = t - 1; i >= 1; i--) {
        if (is_init(b[i])) { s = i + 1; break }
        if (is_agent(b[i]) || is_ts(b[i])) { s = i + 1; break }
    }
    out = ""; att = ""
    for (i = s; i < t; i++) {
        c = b[i]
        if (is_n(c)) continue
        if (out == "" && is_att(c) && i < t - 1) { if (att == "") att = c; continue }
        out = (out == "") ? c : out " " c
        if (length(out) > mc) break
    }
    if (out == "") out = att
    else if (att != "") {
        if (length(att) > 16) att = substr(att, 1, 13) "..."
        out = "[" att "] " out
    }
    return out
}
function heuristic_ctx(    i, c, tp, ar, fb, pc, sa) {
        tp = ""; ar = ""; fb = ""; pc = ""
        for (i = lc; i >= 1; i--) {
            c = b[i]
            if (is_n(c)) continue
            if (is_a(c)) { if (ar == "") ar = c; continue }
            if (tp == "" && length(c) > 8) { tp = c; if (ar != "" || i < lc - 5) break }
            else if (fb == "") fb = c
        }
        for (i = 1; i <= lc; i++) { c = b[i]; if (!is_n(c) && length(c) > 10 && !is_a(c)) { pc = c; break } }
        sa = ar; sub(/^Browsing /, "", sa)
        if (length(sa) > 16) sa = substr(sa, 1, 13) "..."
        if (pc != "" && ar != "")      ctx = "[" sa "] " pc
        else if (tp != "" && ar != "") ctx = "[" sa "] " tp
        else if (pc != "") ctx = pc
        else if (tp != "") ctx = tp
        else if (ar != "") ctx = ar
        else if (fb != "") ctx = fb
        else ctx = "(System Step)"
        return ctx
}
'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
$PROG $VERSION - Abacus.AI transcript credit analyzer

Scans saved Abacus.AI transcript text files (lines like "Credits: 1,653") and
reports file size, total credits and USD value per transcript, plus totals and
mean/median/mode statistics.

Usage:
  $PROG [OPTIONS] [FILE|DIR ...]

With no FILE/DIR, scans the current directory. Directories are scanned
non-recursively; hidden files, *.csv files, binary files and the scanner
itself are skipped automatically (files named explicitly are always used).

Options:
  -d, --dive           Per-transcript breakdown: one row per step/topic.
  -c, --csv            Output CSV instead of tables.
  -s, --sort KEY       Sort order (default: filename). Keys:
                         filename | credits-desc | credits-asc |
                         size | size-asc | words | words-asc |
                         date | date-desc
                       (aliases: name, credits = credits-desc)
  -n, --top N          Only list the first N transcripts after sorting
                       (totals and statistics still cover all files).
  -r, --rate USD       USD price per 10,000 credits (default: 10).
  -t, --tokens-per-word N
                       Ratio used for the Est. Tokens column (default: 1.33,
                       i.e. about 0.75 words per token).
  -p, --pattern GLOB   Filename glob used when scanning directories
                       (default: '*'; e.g. '*-abacusai-transcript.txt').
  -D, --dir DIR        Directory to scan (same as a DIR argument).
      --color WHEN     Bold headings: auto (default), always, never.
      --no-color       Same as --color never (NO_COLOR is also honored).
      --self-test      Check dependencies and run a built-in sanity test.
  -V, --version        Print version and exit.
  -h, --help           Show this help and exit.

Short flags can be combined and take attached values, e.g. -dc, -cs credits-desc, -n5.

Every table and CSV includes Words and Est. Tokens columns. Words are
whitespace-separated words in the transcript text (Credits lines excluded);
Est. Tokens = words x ratio, rounded. It is an estimate, not Abacus.AI's
billed token count: it covers only the saved chat text, not the
background agent work (programming, tool calls, testing) behind the credits.

Examples:
  $PROG                                   # summary of current directory
  $PROG ~/Documents/abacus-ai             # summary of another directory
  $PROG -s credits-desc -n 5              # top five most expensive
  $PROG -d raid-pricer-project-abacusai-transcript.txt
  $PROG -c > credits.csv                  # spreadsheet export
  $PROG --rate 12.5                       # different credit price

Date sort uses a YYYY-MM-DD date in the filename when present, otherwise
the file modification time.

Exit status: 0 success, 1 no transcript files found, 2 usage error.
Project page: $REPO_URL
EOF
}

die()  { printf '%s: error: %s\n' "$PROG" "$1" >&2; printf "Try '%s --help' for more information.\n" "$PROG" >&2; exit 2; }
warn() { printf '%s: warning: %s\n' "$PROG" "$1" >&2; }
run_awk()  { LC_ALL=C "${AWK_CMD[@]}" "$@"; }
run_sort() { LC_ALL=C sort "$@"; }
repeat()   { local out="" i; for ((i = 0; i < $2; i++)); do out+="$1"; done; printf '%s' "$out"; }

# Returns 0 if the file looks binary (grep -I reports no text match on a non-empty file).
is_binary() {
    local rc=0
    [[ -s $1 ]] || return 1
    LC_ALL=C grep -qI '' "$1" 2>/dev/null || rc=$?
    [[ $rc -eq 1 ]]   # rc 2 = grep lacks -I (e.g. busybox): assume text
}

# 14-digit sort key: date from filename (YYYY-MM-DD) or file mtime.
date_key() {
    local name=$1 path=$2 k
    if [[ $name =~ ([0-9]{4})-([0-9]{1,2})-([0-9]{1,2}) ]]; then
        printf '%04d%02d%02d000000' "$((10#${BASH_REMATCH[1]}))" "$((10#${BASH_REMATCH[2]}))" "$((10#${BASH_REMATCH[3]}))"
        return
    fi
    if k=$(date -r "$path" +%Y%m%d%H%M%S 2>/dev/null) && [[ $k =~ ^[0-9]{14}$ ]]; then
        printf '%s' "$k"
    else
        printf '99991231000000'
    fi
}

check_deps() {
    local missing=() c
    for c in "${AWK_CMD[0]}" sort wc grep date mktemp; do
        command -v "$c" >/dev/null 2>&1 || missing+=("$c")
    done
    if ((${#missing[@]})); then
        printf '%s: error: missing required command(s): %s\n' "$PROG" "${missing[*]}" >&2
        return 1
    fi
    # Make sure awk really works (and supports the functions we use).
    local got
    got=$(run_awk "$AWK_LIB"' BEGIN { print cn(1234567.891, 2) }' 2>/dev/null) || got=""
    if [[ $got != "1,234,567.89" ]]; then
        printf '%s: error: awk (%s) failed the formatting check (got "%s").\n' "$PROG" "$AWK_BIN" "$got" >&2
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local dive=0 csv=0 sort_by="filename" top=0 rate="10" tpw="1.33" pattern="*" color="auto"
    local -a targets=()

    while (($#)); do
        case $1 in
            -h|--help)    usage; return 0 ;;
            -V|--version) printf '%s %s\n' "$PROG" "$VERSION"; return 0 ;;
            --self-test)  self_test; return $? ;;
            -d|--dive)    dive=1 ;;
            -w|--words)   ;;   # word counts are always shown now; kept for compatibility
            -c|--csv)     csv=1 ;;
            -s|--sort)    [[ $# -ge 2 ]] || die "option '$1' needs a KEY"; sort_by=$2; shift ;;
            --sort=*)     sort_by=${1#*=} ;;
            -n|--top)     [[ $# -ge 2 ]] || die "option '$1' needs a number"; top=$2; shift ;;
            --top=*)      top=${1#*=} ;;
            -r|--rate)    [[ $# -ge 2 ]] || die "option '$1' needs a USD amount"; rate=$2; shift ;;
            --rate=*)     rate=${1#*=} ;;
            -t|--tokens-per-word) [[ $# -ge 2 ]] || die "option '$1' needs a ratio"; tpw=$2; shift ;;
            --tokens-per-word=*)  tpw=${1#*=} ;;
            -p|--pattern) [[ $# -ge 2 ]] || die "option '$1' needs a GLOB"; pattern=$2; shift ;;
            --pattern=*)  pattern=${1#*=} ;;
            -D|--dir)     [[ $# -ge 2 ]] || die "option '$1' needs a DIR"; targets+=("$2"); shift ;;
            --dir=*)      targets+=("${1#*=}") ;;
            --color)      [[ $# -ge 2 ]] || die "option '$1' needs auto|always|never"; color=$2; shift ;;
            --color=*)    color=${1#*=} ;;
            --no-color)   color="never" ;;
            --)           shift; targets+=("$@"); break ;;
            -[a-zA-Z]?*)   # bundled short flags: -dw -> -d -w ; attached values: -n5, -dn5
                local flags=${1#-} i ch
                local -a split_flags=()
                for ((i = 0; i < ${#flags}; i++)); do
                    ch=${flags:i:1}
                    split_flags+=("-$ch")
                    if [[ $ch == [snrpDt] ]]; then
                        if ((i + 1 < ${#flags})); then split_flags+=("${flags:i+1}"); fi
                        break
                    fi
                done
                shift
                set -- "${split_flags[@]}" "$@"
                continue ;;
            -?*)          die "unknown option '$1'" ;;
            *)            targets+=("$1") ;;
        esac
        shift
    done

    case $sort_by in
        filename|name)       sort_by="filename" ;;
        credits-desc|credits) sort_by="credits-desc" ;;
        credits-asc|size|size-asc|words|words-asc|date|date-desc) ;;
        tokens) sort_by="words" ;;
        tokens-asc) sort_by="words-asc" ;;
        *) die "invalid sort key '$sort_by' (use: filename, credits-desc, credits-asc, size, size-asc, words, words-asc, date, date-desc)" ;;
    esac
    [[ $top =~ ^[0-9]+$ ]] || die "--top expects a non-negative whole number, got '$top'"
    top=$((10#$top))
    [[ $rate =~ ^[0-9]+([.][0-9]+)?$|^[.][0-9]+$ ]] || die "--rate expects a USD amount like 10 or 12.50, got '$rate'"
    [[ $tpw =~ ^[0-9]+([.][0-9]+)?$|^[.][0-9]+$ ]] || die "--tokens-per-word expects a number like 1.33, got '$tpw'"
    case $color in auto|always|never) ;; *) die "--color expects auto, always or never" ;; esac
    [[ -n $pattern ]] || die "--pattern must not be empty"

    check_deps || exit 2

    local B="" R=""
    if [[ $csv -eq 0 ]]; then
        if [[ $color == always ]] || { [[ $color == auto ]] && [[ -t 1 ]] && [[ -z ${NO_COLOR:-} ]] && [[ ${TERM:-dumb} != dumb ]]; }; then
            B=$'\033[1m'; R=$'\033[0m'
        fi
    fi

    local per_credit rate_label
    per_credit=$(run_awk -v r="$rate" 'BEGIN { printf "%.10f", r / 10000 }')
    rate_label=$(run_awk -v r="$rate" 'BEGIN { if (r == int(r)) printf "%d", r; else printf "%.2f", r }')

    # ---- collect files -----------------------------------------------------
    local self_name=${0##*/}
    local -a files=()
    add_file() {   # path explicit
        local f=$1 base=${1##*/}
        if [[ $2 -eq 0 ]]; then
            [[ $base == .* ]] && return 0
            case $base in
                credit-scanner|credit-scanner.sh|"$self_name"|*.csv|*.CSV) return 0 ;;
            esac
            [[ -f $f ]] || return 0
            is_binary "$f" && return 0
        fi
        [[ -r $f ]] || { warn "cannot read '$f', skipping"; return 0; }
        files+=("$f")
    }
    scan_dir() {
        local d=${1%/} f
        [[ -n $d ]] || d="/"
        [[ -r $d && -x $d ]] || { warn "cannot read directory '$1', skipping"; return 0; }
        local IFS=
        shopt -s nullglob
        # shellcheck disable=SC2206  # intentional glob expansion of the pattern
        local -a entries=("$d"/$pattern)
        shopt -u nullglob
        for f in ${entries[@]+"${entries[@]}"}; do add_file "$f" 0; done
    }

    if ((${#targets[@]} == 0)); then
        targets=(".")
    fi
    local t bad=0
    for t in "${targets[@]}"; do
        if [[ -d $t ]]; then scan_dir "$t"
        elif [[ -f $t ]]; then add_file "$t" 1
        elif [[ -e $t ]]; then warn "'$t' is not a regular file or directory, skipping"; bad=1
        else warn "'$t' does not exist"; bad=1
        fi
    done

    if ((${#files[@]} == 0)); then
        printf '%s: no transcript files found in: %s\n' "$PROG" "${targets[*]}" >&2
        [[ $bad -eq 0 ]] && printf "  (hidden files, *.csv and binary files are skipped; pattern: '%s')\n" "$pattern" >&2
        exit 1
    fi

    # ---- analyze -------------------------------------------------------------
    local -a raw=() creds=() wcs=() tks=()
    local f base fn szb cred wcount tkn usd szh fcred fw ft dk max_l=23 g_cred=0 g_bytes=0 g_words=0 g_tok=0
    for f in "${files[@]}"; do
        base=${f##*/}
        fn=${base%.*}
        [[ -n $fn ]] || fn=$base
        ((${#fn} > max_l)) && max_l=${#fn}
        szb=$(wc -c < "$f"); szb=${szb//[[:space:]]/}
        IFS=$'\t' read -r cred wcount tkn usd szh fcred fw ft < <(
            run_awk -v mode=sum -v szb="$szb" -v rate="$per_credit" -v tpw="$tpw" "$AWK_LIB$AWK_TOPIC$AWK_FILE" < "$f"
        )
        dk=$(date_key "$fn" "$f")
        g_cred=$((g_cred + cred)); g_bytes=$((g_bytes + szb)); g_words=$((g_words + wcount)); g_tok=$((g_tok + tkn))
        creds+=("$cred"); wcs+=("$wcount"); tks+=("$tkn")
        raw+=("${cred}${US}${dk}${US}${fn}${US}${fcred}${US}${usd}${US}${szb}${US}${szh}${US}${wcount}${US}${tkn}${US}${fw}${US}${ft}${US}${f}")
    done

    local -a sort_args
    case $sort_by in
        filename)     sort_args=("-k3,3f" "-k3,3") ;;
        credits-desc) sort_args=("-k1,1nr" "-k3,3f") ;;
        credits-asc)  sort_args=("-k1,1n" "-k3,3f") ;;
        size)         sort_args=("-k6,6nr" "-k3,3f") ;;
        size-asc)     sort_args=("-k6,6n" "-k3,3f") ;;
        words)        sort_args=("-k8,8nr" "-k3,3f") ;;
        words-asc)    sort_args=("-k8,8n" "-k3,3f") ;;
        date)         sort_args=("-k2,2n" "-k3,3f") ;;
        date-desc)    sort_args=("-k2,2nr" "-k3,3f") ;;
    esac
    local -a sorted=()
    mapfile -t sorted < <(printf '%s\n' "${raw[@]}" | run_sort -t "$US" "${sort_args[@]}")
    local total_n=${#sorted[@]}
    if ((top > 0 && top < total_n)); then sorted=("${sorted[@]:0:top}"); fi

    local item tot ftot fusd szbr szhr wc_r tk_r fw_r ft_r file
    # ---- dive mode -------------------------------------------------------------
    if [[ $dive -eq 1 ]]; then
        local heavy
        heavy=$(repeat "=" 104)
        if [[ $csv -eq 1 ]]; then
            echo "Filename,FileSizeBytes,TopicSummary,WordCount,EstTokens,Credits,USD"
        fi
        for item in "${sorted[@]}"; do
            IFS=$US read -r tot dk fn ftot fusd szbr szhr wc_r tk_r fw_r ft_r file <<< "$item"
            if [[ $csv -eq 0 ]]; then
                echo "$heavy"
                printf '%s DIVE-IN ANALYSIS: %s (%s)%s\n' "$B" "$fn" "$szhr" "$R"
                echo "$heavy"
                printf "%-42s : %10s : %11s : %15s : %12s\n" "Topic Summary" "Words" "Est. Tokens" "Credit Value" "USD Value"
                printf "%-42s-:-%10s-:-%11s-:-%15s-:-%12s\n" "$(repeat - 42)" "$(repeat - 10)" "$(repeat - 11)" "$(repeat - 15)" "$(repeat - 12)"
            fi
            run_awk -v mode=dive -v fn="$fn" -v szb="$szbr" -v cm="$csv" -v tpw="$tpw" \
                    -v rate="$per_credit" -v B="$B" -v R="$R" "$AWK_LIB$AWK_TOPIC$AWK_FILE" < "$file"
            if [[ $csv -eq 0 ]]; then printf '%s\n\n' "$heavy"; fi
        done
        return 0
    fi

    # ---- totals & statistics -----------------------------------------------------
    local g_fcred g_usd g_szh g_fw g_ft
    IFS=$'\t' read -r g_fcred g_usd g_szh g_fw g_ft < <(
        run_awk -v c="$g_cred" -v b="$g_bytes" -v w="$g_words" -v t="$g_tok" -v rate="$per_credit" \
            "$AWK_LIB"' BEGIN { printf "%s\t%.2f\t%s\t%s\t%s\n", cn(c, 0), c * rate, hs(b), cn(w, 0), cn(t, 0) }'
    )

    # ---- CSV summary -------------------------------------------------------------
    if [[ $csv -eq 1 ]]; then
        echo "FilenameNoExt,FileSizeBytes,FileSizeHuman,WordCount,EstTokens,TotalCredits,USDValue"
        for item in "${sorted[@]}"; do
            IFS=$US read -r tot dk fn ftot fusd szbr szhr wc_r tk_r fw_r ft_r file <<< "$item"
            fn=${fn//\"/\"\"}
            echo "\"$fn\",$szbr,\"$szhr\",$wc_r,$tk_r,$tot,$fusd"
        done
        echo "\"TOTAL\",$g_bytes,\"$g_szh\",$g_words,$g_tok,$g_cred,$g_usd"
        return 0
    fi

    # ---- table summary -------------------------------------------------------------
    local cw=$max_l
    local bl dl
    bl=$(repeat "=" $((cw + 77)))
    dl=$(repeat "-" "$cw")
    echo "$bl"
    printf "%s%-${cw}s : %10s : %10s : %11s : %15s : %12s%s\n" "$B" "Filename (No Extension)" "File Size" "Words" "Est. Tokens" "Total Credits" "USD Value" "$R"
    echo "$bl"
    printf "%-${cw}s-:-%10s-:-%10s-:-%11s-:-%15s-:-%12s\n" "$dl" "$(repeat - 10)" "$(repeat - 10)" "$(repeat - 11)" "$(repeat - 15)" "$(repeat - 12)"
    for item in "${sorted[@]}"; do
        IFS=$US read -r tot dk fn ftot fusd szbr szhr wc_r tk_r fw_r ft_r file <<< "$item"
        printf "%-${cw}s : %10s : %10s : %11s : %15s : \$%10.2f\n" "$fn" "$szhr" "$fw_r" "$ft_r" "$ftot" "$fusd"
    done
    echo "$bl"
    printf "%s%-${cw}s : %10s : %10s : %11s : %15s : \$%10.2f%s\n" "$B" "TOTAL" "$g_szh" "$g_fw" "$g_ft" "$g_fcred" "$g_usd" "$R"
    echo "$bl"
    if ((${#sorted[@]} < total_n)); then
        printf '(Showing top %d of %d transcripts; TOTAL and statistics include all of them.)\n' "${#sorted[@]}" "$total_n"
    fi

    # mean / median / mode per column (mode = most frequent value; ties -> smallest value)
    col_stats() {
        printf '%s\n' "$@" | run_sort -n | run_awk '
            { v[NR] = $1 + 0; s += $1 }
            END {
                n = NR
                md = (n % 2) ? v[(n + 1) / 2] : (v[n / 2] + v[n / 2 + 1]) / 2
                mo = v[1]; mf = 1; cf = 1
                for (i = 2; i <= n; i++) {
                    cf = (v[i] == v[i - 1]) ? cf + 1 : 1
                    if (cf > mf) { mf = cf; mo = v[i] }
                }
                printf "%.4f\t%.4f\t%.0f\n", s / n, md, mo
            }'
    }
    local cs ws ts
    cs=$(col_stats "${creds[@]}"); ws=$(col_stats "${wcs[@]}"); ts=$(col_stats "${tks[@]}")
    local sl
    sl=$(repeat "-" 18)
    printf '\n%sSTATISTICAL SUMMARY (Valuation: $%s per 10,000 credits; Est. Tokens = words x %s):%s\n' "$B" "$rate_label" "$tpw" "$R"
    printf "  %-18s : %15s : %12s : %13s : %13s\n" "Metric" "Credits" "USD Value" "Words" "Est. Tokens"
    printf "  %-18s-:-%15s-:-%12s-:-%13s-:-%13s\n" "$sl" "$(repeat - 15)" "$(repeat - 12)" "$(repeat - 13)" "$(repeat - 13)"
    run_awk -v cs="$cs" -v ws="$ws" -v ts="$ts" -v n="$total_n" -v rate="$per_credit" \
            -v gc="$g_cred" -v gw="$g_words" -v gt="$g_tok" -v B="$B" -v R="$R" "$AWK_LIB"'
        function row(label, c, cd, w, wd, t, td) {
            printf "  %-18s : %15s : $%11.2f : %13s : %13s\n", label, cn(c, cd), c * rate, cn(w, wd), cn(t, td)
        }
        BEGIN {
            split(cs, c, "\t"); split(ws, w, "\t"); split(ts, t, "\t")
            printf "%s", B; row(sprintf("Total (%d file%s)", n, n == 1 ? "" : "s"), gc, 0, gw, 0, gt, 0); printf "%s", R
            row("Mean",   c[1], 2, w[1], 2, t[1], 2)
            row("Median", c[2], 2, w[2], 2, t[2], 2)
            row("Mode",   c[3], 0, w[3], 0, t[3], 0)
        }'
    echo "  Note: Words and Est. Tokens cover only the saved chat transcript text. They do NOT"
    echo "        include the background agent work (programming, tool calls, testing) that the"
    echo "        credits actually paid for, so they understate the real tokens used."
    echo "$bl"
}

# ---------------------------------------------------------------------------
# Built-in self test (used by install.sh to prove the installed copy works)
# ---------------------------------------------------------------------------
self_test() {
    local tmp out fail=0
    check_deps || return 1
    tmp=$(mktemp -d 2>/dev/null || mktemp -d -t credit-scanner)
    cat > "$tmp/self test: sample-abacusai-transcript.txt" <<'EOF'
Create a hello world script in bash for me please
hello.sh
Thought for 12s
Credits: 1,653
Add a clickable table of contents to the README
README.md
Credits: 502
Refactor everything and add a full test suite
Credits: 1,234,567
EOF
    printf 'Credits: 999\n' > "$tmp/.hidden.txt"
    printf 'Credits: 999\n' > "$tmp/export.csv"

    check() {   # description, haystack, needle
        if [[ $2 == *"$3"* ]]; then printf '  ok    %s\n' "$1"
        else printf '  FAIL  %s (expected to find: %s)\n' "$1" "$3"; fail=1; fi
    }
    echo "$PROG $VERSION self-test (awk: $AWK_BIN, bash: $BASH_VERSION)"
    out=$( (main --no-color "$tmp") 2>&1 ) || true
    check "summary total credits" "$out" "1,236,722"
    check "summary USD value"     "$out" "1236.72"
    check "filename with ':'"     "$out" "self test: sample-abacusai-transcript"
    check "words/tokens columns"  "$out" "Est. Tokens"
    check "stats total row"       "$out" "Total (1 file)"
    out=$( (main --no-color --dive "$tmp") 2>&1 ) || true
    check "dive row formatting"   "$out" "1,234,567"
    check "dive project totals"   "$out" "1,236,722"
    if [[ $out == *'\1'* ]]; then printf '  FAIL  %s\n' "dive output contains '\\1' artifacts"; fail=1
    else printf '  ok    %s\n' "no '\\1,\\2' artifacts"; fi
    out=$( (main --csv "$tmp") 2>&1 ) || true
    check "CSV total row"         "$out" '"TOTAL",'
    check "CSV numbers"           "$out" ",1236722,1236.72"
    if [[ $out == *999* ]]; then echo "  FAIL  hidden/CSV files were not skipped"; fail=1
    else echo "  ok    hidden and *.csv files skipped"; fi
    rm -rf "$tmp"
    if [[ $fail -eq 0 ]]; then echo "self-test: OK"; return 0; fi
    echo "self-test: FAILED"; return 1
}

main "$@"
