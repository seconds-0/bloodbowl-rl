#!/usr/bin/env bash
# Dedicated checkout for the b3 arm: own repo tree, own PufferLib tree, own venv copy. Made the way
# /home/rache/bbopt-20261001/make_longrun_checkout.sh made the long-run checkout, with one addition: the
# copied venv's entrypoint shebangs are repointed as well as its editable finder.
#
# It reads the source checkout and writes only under the new path. CPU only until the final import check,
# which loads the compiled module once. Run it once; it refuses an existing target.
#
#   bash make_b3_checkout.sh [git ref]        default origin/feat/no-early-end-turn-20261005
set -euo pipefail
S="${B3_SOURCE_CHECKOUT:-/home/rache/bloodbowl-rl-qualification-candidate-10619e2}"
C2="${B3_C:-/home/rache/bloodbowl-rl-b3-20261006}"
REF="${1:-origin/feat/no-early-end-turn-20261005}"
if [ -e "$C2" ]; then echo "$C2 already exists; refusing"; exit 2; fi
[ -d "$S/vendor/PufferLib/.venv" ] || { echo "no venv to copy at $S/vendor/PufferLib/.venv"; exit 2; }
git clone -q "$S" "$C2"
cd "$C2"
git remote set-url origin "$(git -C "$S" remote get-url origin)"
git fetch -q origin
git checkout -q "$REF"
git log --oneline -1
mkdir -p vendor/PufferLib runs
rsync -a --exclude build --exclude .venv --exclude checkpoints --exclude logs --exclude experiments "$S/vendor/PufferLib/" "$C2/vendor/PufferLib/"
echo "copying venv (7 GB)"; cp -a "$S/vendor/PufferLib/.venv" "$C2/vendor/PufferLib/.venv"
V="$C2/vendor/PufferLib/.venv"
SITE="$V/lib/python3.11/site-packages"
F="$SITE/__editable___pufferlib_4_0_0_finder.py"
grep -n "MAPPING: dict" "$F" | cut -c1-200
# The finder decides which pufferlib `python` imports; the shebangs decide which venv an ENTRYPOINT runs in.
# cp -a keeps both pointing at the venv this one was copied from. The long-run checkout was made with the
# finder repointed and the shebangs not, so its `puffer` entrypoint runs in the source checkout's venv.
sed -i "s#${S}/#${C2}/#g" "$F"
{ grep -rlI "${S}/vendor/PufferLib/.venv" "$V/bin" || true; } | while IFS= read -r file; do
  sed -i "s#${S}/vendor/PufferLib/.venv#${V}#g" "$file"
done
echo "still naming the source checkout (informational files only are expected):"
grep -rlI "$S" "$V/bin" "$SITE"/*.pth "$SITE/pufferlib-4.0.0.dist-info" "$F" 2>/dev/null | head || true
head -n 1 "$V/bin/puffer"
[ "$(head -n 1 "$V/bin/puffer")" = "#!$V/bin/python" ] || { echo "the puffer entrypoint does not run in the new venv"; exit 1; }
grep -q "'pufferlib': '$C2/vendor/PufferLib/pufferlib'" "$F" || { echo "the editable finder does not point at the new tree"; exit 1; }
PYD="$V/bin"
export PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1 CUDA_VISIBLE_DEVICES=0
PATH="$PYD:$PATH" bash tools/install_puffer_env.sh > "$C2/runs/install_b3.log" 2>&1; echo "install rc=$?"
grep -E "^applied|^reversed" "$C2/runs/install_b3.log" | tail -4
cat vendor/PufferLib/ocean/bloodbowl/.content_hash; echo
( cd vendor/PufferLib && PATH="$PYD:$PATH" nice -n 5 ./build.sh bloodbowl --float > "$C2/runs/build_b3.log" 2>&1 ); echo "build rc=$?"
PATH="$PYD:$PATH" bash tools/install_puffer_env.sh --check 2>&1 | tail -3
cd /
# The same import through both doors: the venv's python, and the interpreter the entrypoint names.
for interpreter in "$PYD/python" "$(head -n 1 "$V/bin/puffer" | sed 's/^#!//')"; do
"$interpreter" - "$C2" <<"PY"
import hashlib, pathlib, sys
import pufferlib
from pufferlib import _C
root = pathlib.Path(sys.argv[1])
print("interpreter:", sys.executable)
print("pufferlib:", pufferlib.__file__)
print("_C:", _C.__file__, _C.precision_bytes, getattr(_C, "scripted_bank_forward_skip", None))
print("module sha256:", hashlib.sha256(open(_C.__file__, "rb").read()).hexdigest())
installed = (root / "vendor/PufferLib/ocean/bloodbowl/.content_hash").read_text().strip()
assert pathlib.Path(_C.__file__).resolve().is_relative_to(root.resolve()), "the module is not this checkout's"
assert _C.environment_source_hash == installed, (_C.environment_source_hash, installed)
print("environment source:", installed, "(compiled == installed)")
PY
done
echo B3_CHECKOUT_DONE
