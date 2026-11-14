#!/usr/bin/env bash
# Alle Tests. Braucht PySide6, pyqtgraph, bleak, pyserial.
set -euo pipefail
cd "$(dirname "$0")/.."
export QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen}
for t in tests/test_*.py; do
  echo "== $t"
  python "$t"
done
python start.py --pruefen
python start.py --fenster-probe
echo "Alle Tests grün."
