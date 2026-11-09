#!/usr/bin/env bash
# Run in tri-oracle-eda with the vendor process package mounted at /pdks.
set -euo pipefail
source_library=/pdks/tsmc28hpc/pdk/Techfile/online/1P10M_5X2Y2Z/techfile_lib_pcell/tsmcN28
mkdir -p .cache/physical/oa/tri_tech .cache/physical/library
cp "$source_library/tech.db" .cache/physical/oa/tri_tech/tech.db
printf 'DEFINE tri_tech %s/.cache/physical/oa/tri_tech\nDEFINE tsmcN28 %s\n' \
    "$PWD" "$source_library" > .cache/physical/oa/lib.defs
oa2lef -lib tri_tech -libDefFile .cache/physical/oa/lib.defs \
    -lef .cache/physical/library/technology_1p10m_5x2y2z.lef \
    -logFile .cache/physical/oa/oa2lef.log > .cache/physical/oa/console.log 2>&1
grep -q '0 errors' .cache/physical/oa/console.log
