import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

nb = json.load(open(r"notebooks/Hunyuan3D-2.1_i23d_pbr_local.ipynb", encoding="utf-8"))
print("celdas:", len(nb["cells"]))
for i, c in enumerate(nb["cells"]):
    print(i, c["cell_type"], repr("".join(c["source"])[:90]))
