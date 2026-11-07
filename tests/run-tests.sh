#!/usr/bin/env bash
# Test suite for credit-scanner. Usage: tests/run-tests.sh
# Runs every check once per awk implementation found (awk, gawk, mawk,
# original-awk/nawk, busybox awk). Set TEST_AWKS="gawk mawk" to choose.
# SPDX-License-Identifier: GPL-3.0-or-later
# shellcheck disable=SC2016  # literal '$' in expected output strings
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$HERE")
SCANNER="$ROOT/credit-scanner.sh"
EXP="$HERE/expected"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Stage fixtures in a temp dir. ':' is not allowed in filenames on Windows,
# so the repo stores it as __COLON__ and the real name is created here.
FIX="$TMP/fixtures"
cp -R "$HERE/fixtures" "$FIX"
for f in "$FIX"/*__COLON__*; do
    [[ -e $f ]] && mv "$f" "${f//__COLON__/:}"
done

pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  \033[31mFAIL\033[0m  %s\n' "$1"; [[ -n ${2:-} ]] && printf '%s\n' "$2" | sed 's/^/        /'; }

run() { CREDIT_SCANNER_AWK="$AWK_IMPL" bash "$SCANNER" --no-color "$@"; }

assert_contains() {   # name haystack needle
    if [[ $2 == *"$3"* ]]; then ok "$1"; else bad "$1" "expected to contain: $3"$'\n'"--- got ---"$'\n'"$2"; fi
}
assert_not_contains() {
    if [[ $2 != *"$3"* ]]; then ok "$1"; else bad "$1" "must not contain: $3"; fi
}
assert_eq() {
    if [[ $2 == "$3" ]]; then ok "$1"; else bad "$1" "expected: $3"$'\n'"got:      $2"; fi
}
assert_golden() {     # name output expected-file
    # command substitution strips trailing newlines, so compare both sides that way
    if diff -u <(printf '%s\n' "$(cat "$3")") <(printf '%s\n' "$2") >"$TMP/diff" 2>&1; then ok "$1"
    else bad "$1" "$(cat "$TMP/diff")"; fi
}
assert_status() {     # name expected-status cmd...
    local name=$1 want=$2; shift 2
    "$@" >/dev/null 2>&1; local got=$?
    assert_eq "$name" "$got" "$want"
}

if [[ -n ${TEST_AWKS:-} ]]; then
    read -ra AWKS <<< "$TEST_AWKS"
else
    AWKS=()
    for a in awk gawk mawk original-awk nawk; do command -v "$a" >/dev/null 2>&1 && AWKS+=("$a"); done
    command -v busybox >/dev/null 2>&1 && busybox awk 'BEGIN{}' 2>/dev/null && AWKS+=("busybox awk")
fi

for AWK_IMPL in "${AWKS[@]}"; do
    echo "=== awk implementation: $AWK_IMPL"

    # Real Abacus.AI transcript layout: initials / prompt / time / "Abacus AI Agent" / ... / Credits
    real="$HERE/fixtures-real/real-format-project-abacusai-transcript.txt"
    out=$(run -d "$real")
    assert_golden    "real-format dive labels use the user prompt" "$out" "$EXP/real-dive.txt"
    assert_not_contains "real-format: no agent-name labels" "$out" "Abacus AI Agent"
    assert_not_contains "real-format: no initials labels" "$out" "[AG]"
    assert_contains  "real-format: attachment with spaces bracketed" "$out" "[image (1).png] It mostly works"
    assert_contains  "real-format: cancelled turn -> last prompt" "$out" "OK, getting this: ✔ nixos-rebuild"
    assert_contains  "real-format: totals" "$out" "4,669"
    out=$(run -dc "$real")
    assert_golden    "real-format dive CSV" "$out" "$EXP/real-dive.csv"

    out=$(run "$FIX"); rc=$?
    assert_eq        "summary exits 0" "$rc" 0
    assert_golden    "summary table matches golden output" "$out" "$EXP/summary.txt"
    assert_not_contains "hidden/csv/self/binary files skipped" "$out" "99,999"

    out=$(run --dive "$FIX")
    assert_golden    "dive table matches golden output" "$out" "$EXP/dive.txt"
    assert_not_contains "dive has no \\1,\\2 artifacts" "$out" '\1'
    assert_contains  "dive project totals formatted" "$out" "PROJECT TOTALS                             :         12 :          16 :       1,234,567 : \$   1234.57"
    assert_contains  "dive trailing-text row" "$out" "(text after last Credits line)"
    assert_contains  "dive no-credits row" "$out" "(no Credits lines found)"

    out=$(run --dive --words "$FIX")
    assert_golden    "-w is a compatible no-op (dive)" "$out" "$EXP/dive.txt"

    out=$(run --csv "$FIX")
    assert_golden    "summary CSV matches golden output" "$out" "$EXP/summary.csv"

    out=$(run --csv --dive "$FIX")
    assert_golden    "dive CSV matches golden output" "$out" "$EXP/dive.csv"

    out=$(run -cw "$FIX")
    assert_contains  "bundled -cw still accepted" "$out" '"TOTAL",619,"619 B",85,114,1255787,1255.79'

    out=$(run "$FIX")
    assert_contains  "summary has Words/Est. Tokens headers" "$out" ":      Words : Est. Tokens :"
    assert_contains  "stats total row" "$out" "Total (4 files)    :       1,255,787 : \$    1255.79 :            85 :           114"
    assert_contains  "stats mean row"  "$out" "Mean               :      313,946.75 : \$     313.95 :         21.25 :         28.50"
    assert_contains  "stats median row" "$out" "Median             :       10,610.00 : \$      10.61 :         19.00 :         25.50"
    assert_contains  "stats mode row"  "$out" "Mode               :               0 : \$       0.00 :             6 :             8"
    assert_contains  "stats token-scope note" "$out" "do NOT"

    out=$(run -c -t 2 "$FIX" | tail -n 1)
    assert_eq        "--tokens-per-word 2" "$out" '"TOTAL",619,"619 B",85,170,1255787,1255.79'
    out=$(run -c --tokens-per-word=1 "$FIX" | tail -n 1)
    assert_eq        "--tokens-per-word=1" "$out" '"TOTAL",619,"619 B",85,85,1255787,1255.79'
    assert_status    "bad --tokens-per-word exits 2" 2 run -t abc "$FIX"
    out=$(run -c -s words "$FIX" | sed -n 2p)
    assert_contains  "sort words" "$out" '"raid-pricer-project-abacusai-transcript"'
    out=$(run -c -s tokens-asc "$FIX" | sed -n 2p)
    assert_contains  "sort tokens-asc" "$out" '"notes-without-credits"'
    out=$(run -dc "$FIX" | awk -F, 'NR>1 && $1 ~ /xtree/ {w+=$(NF-3); t+=$(NF-2)} END {print w}')
    assert_eq        "dive word rows add up to file total" "$out" 12

    out=$(run -c -s credits-desc "$FIX" | sed -n 2p)
    assert_contains  "sort credits-desc" "$out" '"xtree project-abacusai-transcript"'
    out=$(run -c --sort=credits-asc "$FIX" | sed -n 2p)
    assert_contains  "sort credits-asc" "$out" '"notes-without-credits"'
    out=$(run -c -s size "$FIX" | sed -n 2p)
    assert_contains  "sort size" "$out" '"raid-pricer-project-abacusai-transcript"'

    out=$(run -n 2 -s credits "$FIX")
    assert_contains  "--top limits rows" "$out" "Showing top 2 of 4 transcripts"
    assert_not_contains "--top hides the rest" "$out" "notes-without-credits "
    assert_contains  "--top keeps full TOTAL" "$out" "1,255,787"

    out=$(run -cn1 -scredits "$FIX")
    assert_eq        "attached values (-cn1 -scredits)" "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" 3
    assert_contains  "attached sort value applied" "$out" '"xtree project-abacusai-transcript"'

    out=$(run --rate 20 -c "$FIX" | tail -n 1)
    assert_eq        "--rate 20 doubles USD" "$out" '"TOTAL",619,"619 B",85,114,1255787,2511.57'
    out=$(run --rate 12.5 "$FIX")
    assert_contains  "--rate label" "$out" 'Valuation: $12.50 per 10,000 credits'

    out=$(run -c "$FIX/xtree project-abacusai-transcript.txt" "$FIX/barcode-splitter: invoice-project-abacusai-transcript.txt")
    assert_contains  "multiple FILE args (spaces and ':')" "$out" '"TOTAL",276,"276 B",38,51,1240787,1240.79'

    out=$(run -c "$FIX/.hidden-transcript.txt")
    assert_contains  "explicit hidden file is honored" "$out" ',99999,100.00'

    out=$(run -c -p '*-abacusai-transcript.txt' --dir "$FIX")
    assert_not_contains "--pattern filters files" "$out" "notes-without-credits"

    out=$(cd "$FIX" && run -c | tail -n 1)
    assert_eq        "no args scans current directory" "$out" '"TOTAL",619,"619 B",85,114,1255787,1255.79'

    mkdir -p "$TMP/dated"
    printf 'Credits: 1\n' > "$TMP/dated/b-2026-11-05-transcript.txt"
    printf 'Credits: 2\n' > "$TMP/dated/a-2026-09-30-transcript.txt"
    printf 'Credits: 3\n' > "$TMP/dated/c-2026-08-01-transcript.txt"
    out=$(run -c -s date "$TMP/dated" | sed -n 2p)
    assert_contains  "sort date (filename dates, 08 is not octal)" "$out" '"c-2026-08-01-transcript"'
    out=$(run -c -s date-desc "$TMP/dated" | sed -n 2p)
    assert_contains  "sort date-desc" "$out" '"b-2026-11-05-transcript"'

    printf 'Credits: 2,000,000,000\nCredits: 2,000,000,000\n' > "$TMP/big.txt"
    out=$(run -c "$TMP/big.txt" | tail -n 1)
    assert_contains  "large totals do not overflow" "$out" ',4000000000,4000000.00'
    out=$(run -d "$TMP/big.txt")
    assert_contains  "large dive totals formatted" "$out" "4,000,000,000"

    printf 'Credits: 1,653 (about $1.65)\n' > "$TMP/trailing.txt"
    out=$(run -c "$TMP/trailing.txt" | tail -n 1)
    assert_contains  "only the number after Credits: is used" "$out" ',1653,1.65'

    mkdir -p "$TMP/empty"
    assert_status    "empty directory exits 1" 1 run "$TMP/empty"
    assert_status    "missing file exits 1" 1 run "$TMP/does-not-exist.txt"
    assert_status    "unknown option exits 2" 2 run --bogus
    assert_status    "bad sort key exits 2" 2 run -s sideways "$FIX"
    assert_status    "bad --top exits 2" 2 run -n abc "$FIX"
    assert_status    "bad --rate exits 2" 2 run --rate ten "$FIX"
    assert_status    "missing option value exits 2" 2 run -s
    assert_status    "--help exits 0" 0 run --help
    out=$(run --version)
    assert_contains  "--version" "$out" "credit-scanner "
    assert_status    "--self-test passes" 0 run --self-test
done

echo "=== installer"
inst="$TMP/prefix"
out=$(bash "$ROOT/install.sh" --from "$SCANNER" --prefix "$inst" 2>&1); rc=$?
assert_eq        "install.sh exits 0" "$rc" 0
assert_contains  "install.sh verifies installed copy" "$out" "self-test passed"
if [[ -x $inst/bin/credit-scanner ]]; then ok "installed file is executable"; else bad "installed file is executable"; fi
out=$("$inst/bin/credit-scanner" -c "$FIX" | tail -n 1)
assert_eq        "installed command works" "$out" '"TOTAL",619,"619 B",85,114,1255787,1255.79'
bash "$ROOT/install.sh" --prefix "$inst" --uninstall >/dev/null 2>&1
if [[ ! -e $inst/bin/credit-scanner ]]; then ok "uninstall removes the command"; else bad "uninstall removes the command"; fi
printf '#!/usr/bin/env bash\necho not the scanner\n' > "$TMP/fake.sh"
assert_status    "installer rejects a wrong/broken script" 1 bash "$ROOT/install.sh" --from "$TMP/fake.sh" --prefix "$inst"
if [[ ! -e $inst/bin/credit-scanner ]]; then ok "nothing installed after rejected script"; else bad "nothing installed after rejected script"; fi

echo
echo "passed: $pass  failed: $fail  (awks: ${AWKS[*]})"
[[ $fail -eq 0 ]]
