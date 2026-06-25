#!/usr/bin/env bash
# Render every *.html in a folder to PNG pages for visual review.
# Folder-general sibling of docs/preview.sh, used by the review-html skill.
#
# Usage:
#   render.sh [folder]            # default folder: docs
#
# Output: a unique temp dir holding <name>.pdf and <name>-N.png per HTML file.
# Stdout is a manifest the skill parses:
#   <rel-html-path>\t<png1> <png2> ...
#   ...
#   # outdir: <temp-dir>
# Claude then Read's the PNG pages to inspect them visually.

set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FOLDER="${1:-docs}"

if [ ! -x "$CHROME" ]; then
  echo "error: Google Chrome not found at $CHROME" >&2
  exit 1
fi

if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "error: pdftoppm not found. Install poppler: brew install poppler" >&2
  echo "       (docs/preview.sh is the docs-only equivalent)" >&2
  exit 1
fi

# Resolve the folder to an absolute path (relative to CWD).
abs_folder="$(cd "$FOLDER" 2>/dev/null && pwd)" || {
  echo "error: folder '$FOLDER' not found" >&2
  exit 1
}

shopt -s nullglob
html_files=("$abs_folder"/*.html)
if [ "${#html_files[@]}" -eq 0 ]; then
  echo "error: no *.html files in $FOLDER" >&2
  exit 1
fi

OUT="$(mktemp -d -t html-review)"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

for html in "${html_files[@]}"; do
  name="$(basename "${html%.html}")"
  pdf="$OUT/$name.pdf"
  "$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="$pdf" "file://$html" >&2
  pdftoppm -png -r 120 "$pdf" "$OUT/$name" >&2

  # Relative path for the manifest when inside the repo.
  rel="${html#$repo_root/}"
  pngs=("$OUT/$name"-*.png)
  printf '%s\t%s\n' "$rel" "${pngs[*]}"
done

echo "# outdir: $OUT"
