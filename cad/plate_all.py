"""Put every printed part on one build plate -> cad/all_parts.stl and cad/all_parts.3mf

    ~/Gabriel/ameta_s20/.venv/bin/python cad/plate_all.py
(run cad/pin_release.py and cad/stands.py first). Parts: release v2 x1, rear stand x2, front leg extension x2.
"""
import os
import trimesh

here = os.path.dirname(os.path.abspath(__file__))
parts = [("pin_release_v2.stl", 1), ("rear_stand.stl", 2), ("front_leg_extension.stl", 2)]
GAP = 8.0

meshes, x = [], 0.0
for name, count in parts:
    for i in range(count):
        m = trimesh.load(os.path.join(here, name))
        m.apply_translation(-m.bounds[0])                  # min corner to origin, feet on z = 0
        m.apply_translation([x, 0, 0])
        x += m.extents[0] + GAP
        m.metadata["name"] = f"{os.path.splitext(name)[0]}_{i + 1}"
        meshes.append(m)
combined = trimesh.util.concatenate(meshes)
combined.apply_translation([-combined.bounds[0][0] - combined.extents[0] / 2, -combined.extents[1] / 2, 0])
combined.export(os.path.join(here, "all_parts.stl"))
scene = trimesh.Scene()
offset = combined.bounds[0]  # not used; keep each part's own placement
for m in meshes:
    m.apply_translation([-x / 2 + GAP / 2, -m.extents[1] / 2, 0])
    scene.add_geometry(m, node_name=m.metadata["name"])
try:
    scene.export(os.path.join(here, "all_parts.3mf"))
    print("wrote cad/all_parts.3mf")
except Exception as e:
    print("3mf skipped:", e)
print(f"wrote cad/all_parts.stl: {combined.extents[0]:.0f} x {combined.extents[1]:.0f} x {combined.extents[2]:.0f} mm, "
      f"{len(meshes)} parts")
