"""Pin-pull payload release for the AMETA S20 Lite harness -- generates pin_release.stl.

    ~/Gabriel/ameta_s20/.venv/bin/python cad/pin_release.py              # 2 mm rod pin -> cad/pin_release.stl
    ~/Gabriel/ameta_s20/.venv/bin/python cad/pin_release.py --pin-d 1.0  # paper-clip pin -> cad/pin_release_pin1.0.stl

Print orientation = as generated (plate flat on the bed, no supports). It mounts UPSIDE DOWN under the drone:
plate against the drone's belly, strapped through the two slots; servo and fins point at the ground.

    servo horn ──wire link──► pin ══╦═══════╦══   pin slides through both fin holes
                                   fin1  gap  fin2
                                         │
                                    payload loop  (hangs on the pin in the gap)

Release = servo pulls the pin back out of fin2; the loop slides off. The payload's weight sits on the
pin and fins, not on the servo.

MEASURE YOUR SERVO (calipers) and edit the SERVO_* numbers before printing. All sizes in mm.
"""
import argparse, os
import numpy as np
import trimesh
from manifold3d import Manifold

# ---- servo (GH-S37D 3.7 g -- typical values, MEASURE yours) -------------------------------------
SERVO_L = 20.0        # body length without mounting tabs (measured 20 mm)
SERVO_W = 8.5         # body width
SERVO_H = 25.0        # base to the top of the output gear where the arm sits (measured 25 mm)
TAB_SPAN = 30.0       # length across the mounting tabs (measured 30 mm)
END_LIP = 3.0         # cradle end walls are only this tall, so the tabs clear them
SHAFT_OFFSET = 5.0    # output shaft centre, measured from the body's END nearest the fins
HORN_R = 10.0         # half the arm length (arm measured 20 mm across)

# ---- pin and payload ---------------------------------------------------------------------------
PIN_D = 2.0           # pin diameter (paper clip ~1.0, steel rod 2.0, bamboo skewer ~2.5)
PIN_CLEAR = 0.35      # hole is PIN_D + this (sliding fit)
LOOP_GAP = 7.0        # space between the fins where the payload loop hangs
PIN_Z = SERVO_H + 0.5 # pin height above the plate (≈ arm height so the wire link is straight)

# ---- printing ----------------------------------------------------------------------------------
CLEAR = 0.3           # servo pocket clearance per side
WALL = 1.2            # cradle wall
PLATE_T = 2.0         # plate thickness
CRADLE_H = 8.0        # cradle wall height (holds the servo's lower half; glue it in)
FIN_T = 2.6           # fin thickness (along the pin)
FIN_W = 9.0           # fin width
SLOT = (2.6, 9.0)     # strap slot size (x, y) -- zip tie / rubber band
SEG = 48              # circle smoothness

_ap = argparse.ArgumentParser()
_ap.add_argument("--pin-d", type=float, default=None, help="pin diameter in mm (overrides PIN_D)")
_a = _ap.parse_args()
if _a.pin_d:
    PIN_D = _a.pin_d


def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def x_hole(x0, x1, y, z, d):
    """Cylinder along X (for the pin holes)."""
    return Manifold.cylinder(x1 - x0, d / 2, d / 2, SEG).rotate([0, 90, 0]).translate([x0, y, z])


# ---- layout along X: [slot] [cradle][horn clearance][fin1][gap][fin2] [slot] ------------------
in_l, in_w = SERVO_L + 2 * CLEAR, SERVO_W + 2 * CLEAR
cr_x0, cr_x1 = 0.0, in_l + 2 * WALL
shaft_x = cr_x1 - WALL - CLEAR - SHAFT_OFFSET
fin1_x0 = max(cr_x1 + 1.0, shaft_x + HORN_R + 1.5, cr_x0 + WALL + CLEAR + SERVO_L / 2 + TAB_SPAN / 2 + 1.0)  # clear horn swing + tab
fin1_x1 = fin1_x0 + FIN_T
fin2_x0 = fin1_x1 + LOOP_GAP
fin2_x1 = fin2_x0 + FIN_T
half_w = max(in_w / 2 + WALL, FIN_W / 2) + 3.0
px0, px1 = cr_x0 - SLOT[0] - 4.0, fin2_x1 + SLOT[0] + 4.0

plate = box(px0, px1, -half_w, half_w, 0, PLATE_T)
for sx in (px0 + 2.0, px1 - 2.0 - SLOT[0]):                  # strap slots at both ends
    plate -= box(sx, sx + SLOT[0], -SLOT[1] / 2, SLOT[1] / 2, -1, PLATE_T + 1)

cradle = box(cr_x0, cr_x1, -in_w / 2 - WALL, in_w / 2 + WALL, 0, PLATE_T + CRADLE_H)
cradle -= box(cr_x0 + WALL, cr_x1 - WALL, -in_w / 2, in_w / 2, PLATE_T, PLATE_T + CRADLE_H + 1)
for ex0, ex1 in ((cr_x0 - 1, cr_x0 + WALL + 0.01), (cr_x1 - WALL - 0.01, cr_x1 + 1)):   # low end walls: tabs pass over
    cradle -= box(ex0, ex1, -in_w / 2 - WALL - 1, in_w / 2 + WALL + 1, PLATE_T + END_LIP, PLATE_T + CRADLE_H + 1)
cradle -= box(cr_x0 - 1, cr_x0 + WALL + 1, -2.0, 2.0, PLATE_T, PLATE_T + 4.0)   # wire exit notch (far end)

pin_z = PLATE_T + PIN_Z
fin_top = pin_z + PIN_D / 2 + 3.0
fins = Manifold()
for fx0, fx1 in ((fin1_x0, fin1_x1), (fin2_x0, fin2_x1)):
    fin = box(fx0, fx1, -FIN_W / 2, FIN_W / 2, 0, fin_top)
    # gussets (outer side of each fin) so the fin doesn't snap off the plate
    for side in (-1, 1):
        g = Manifold.cube([FIN_T, 2.0, fin_top * 0.6]).translate([fx0, side * (FIN_W / 2) - (0 if side > 0 else 2.0), 0])
        fin += g
    fins += fin
fins -= x_hole(fin1_x0 - 1, fin2_x1 + 1, 0, pin_z, PIN_D + PIN_CLEAR)

part = plate + cradle + fins

mesh = part.to_mesh()
tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, "pin_release.stl" if not _a.pin_d else f"pin_release_pin{PIN_D:g}.stl")
tm.export(out)

vol_cm3 = tm.volume / 1000
print(f"wrote {out}")
print(f"size: {tm.extents[0]:.1f} x {tm.extents[1]:.1f} x {tm.extents[2]:.1f} mm, watertight={tm.is_watertight}")
print(f"solid volume {vol_cm3:.2f} cm3 -> about {vol_cm3 * 1.24:.1f} g PLA solid, ~{vol_cm3 * 1.24 * 0.6:.1f} g at 15-20% infill")
print(f"pin travel needed to release: {FIN_T + LOOP_GAP + 1:.1f} mm (pull the pin out of fin2 and across the gap)")
print(f"horn shaft at x={shaft_x:.1f}, fin1 starts x={fin1_x0:.1f}  (horn reach {HORN_R} mm + 1.5 clearance)")

# preview image
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(9, 5))
    for i, (elev, azim) in enumerate(((28, -60), (90, -90))):
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.add_collection3d(Poly3DCollection(tm.vertices[tm.faces], facecolor="#8fb3d9", edgecolor="#2b4a6b", linewidths=0.1))
        mn, mx = tm.bounds
        span = (mx - mn).max()
        c = (mx + mn) / 2
        for setlim, k in ((ax.set_xlim, 0), (ax.set_ylim, 1), (ax.set_zlim, 2)):
            setlim(c[k] - span / 2, c[k] + span / 2)
        ax.view_init(elev, azim)
        ax.set_title("3D view" if i == 0 else "top view")
        ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(out.replace(".stl", "_preview.png"), dpi=130)
    print("wrote preview", out.replace(".stl", "_preview.png"))
except Exception as e:
    print("preview skipped:", e)
