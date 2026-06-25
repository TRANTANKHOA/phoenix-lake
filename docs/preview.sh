#!/usr/bin/env bash
# Render docs/*.html to PDF using headless Google Chrome, for visual review.
#
# Usage:
#   docs/preview.sh                       # render every docs/*.html -> /tmp/<name>.pdf
#   docs/preview.sh docs/dbt.html         # render one file  -> /tmp/dbt.pdf
#   docs/preview.sh dbt                   # basename shorthand-> /tmp/dbt.pdf
#   docs/preview.sh docs/dbt.html out.pdf # render one file  -> out.pdf
#
# Output defaults to /tmp/<basename>.pdf so the repo stays clean.
# Claude can then `Read` the PDF to inspect the rendered page visually.

set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -x "$CHROME" ]; then
  echo "error: Google Chrome not found at $CHROME" >&2
  echo "install Chrome, or edit CHROME in this script to point at another browser" >&2
  exit 1
fi

# resolve <input> -> absolute path to an existing .html file
resolve_html() {
  local input="$1"
  for candidate in "$input" "$REPO_ROOT/$input" "$REPO_ROOT/docs/$input" "$REPO_ROOT/docs/$input.html"; do
    if [ -f "$candidate" ]; then
      echo "$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
      return 0
    fi
  done
  echo "error: '$input' not found (tried as path, basename, and docs/<name>[.html])" >&2
  exit 1
}

render() {
  local html="$1"
  local out="${2:-/tmp/$(basename "${html%.html}").pdf}"
  local stem="${out%.pdf}"
  "$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="$out" "file://$html" >&2
  echo "  pdf   $out"
  # Split the PDF into PNG pages so Claude's Read tool can view them directly,
  # without depending on its built-in PDF renderer (which needs poppler on PATH).
  if command -v pdftoppm >/dev/null 2>&1; then
    pdftoppm -png -r 120 "$out" "$stem" >&2
    echo "  pages ${stem}-*.png"
  else
    echo "  (install poppler, or restart Claude Code, to get readable PNG pages)"
  fi
}

if [ "$#" -eq 0 ]; then
  shopt -s nullglob
  files=("$REPO_ROOT"/docs/*.html)
  if [ "${#files[@]}" -eq 0 ]; then
    echo "error: no docs/*.html found in $REPO_ROOT/docs" >&2
    exit 1
  fi
  for f in "${files[@]}"; do
    render "$f" >/dev/null
  done
  echo "done: rendered ${#files[@]} file(s) to /tmp"
else
  html="$(resolve_html "$1")"
  render "$html" "${2:-}"
fi
