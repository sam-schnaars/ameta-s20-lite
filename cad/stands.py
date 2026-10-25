"""Landing-gear raisers for the AMETA S20 Lite, so the belly has room for the release + payload.

    ~/Gabriel/ameta_s20/.venv/bin/python cad/stands.py
    -> cad/rear_stand.stl          print 2  (cup wraps the round rear motor pod, leg to the floor)
    -> cad/front_leg_extension.stl print 2  (sleeve slides over each front leg tip)
    -> cad/stands_preview.png

Idea: lift the WHOLE drone by LIFT mm so it stays level and stands on 4 points (2 front legs + 2 rear stands)
instead of the front legs + the belly "teeth". Print upright (foot on the bed), no supports.
MEASURE and edit the marked numbers before the final print; print one of each first as a fit test.
All sizes in mm.
"""
import os
import numpy as np
import trimesh
from manifold3d import Manifold

IN = 25.4
LIFT = 31.0                 # extra height for the whole drone = height of the old release's fins (~31 mm)

# ---- rear motor pod (photo 3)  -- MEASURE ---------------------------------------------------------
POD_D = 24.0                # diameter of the round pod end, seen from below (~0.95 in in the photo)
ARM_W = 15.0                # width of the arm where it joins the pod
POD_FLOOR = 0.25 * IN       # floor -> bottom of the rear pod with the drone sitting normally (user: 1/4 in)
BUMP_L, BUMP_W, BUMP_H = 9.0, 6.5, 3.0   # small rectangular bump under the pod (length along arm, width, height)

# ---- front leg tip -- MEASURE ----------------------------------------------------------------------
TIP_W, TIP_T = 9.0, 5.0     # front leg tip: width x thickness about 10 mm up from the bottom
SOCK_D = 10.0               # how far the leg slides into the sleeve

# ---- printing ----------------------------------------------------------------------------------------
CLEAR = 0.3                 # fit clearance per side
WALL = 1.6
FOOT_D = 18.0               # foot pad diameter (wider = steadier landings)
SEG = 64


def cyl(h, r1, r2=None, z=0.0):
    return Manifold.cylinder(h, r1, r1 if r2 is None else r2, SEG).translate([0, 0, z])


def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def export(m, name):
    mesh = m.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    tm.export(path)
    g = tm.volume / 1000 * 1.24 * 0.6          # PLA, ~15-20% infill estimate
    print(f"wrote {path}: {tm.extents[0]:.1f} x {tm.extents[1]:.1f} x {tm.extents[2]:.1f} mm, "
          f"watertight={tm.is_watertight}, ~{g:.1f} g printed")
    return tm


# ---- rear stand: pod cup on a leg ---------------------------------------------------------------------
seat_z = POD_FLOOR + LIFT          # pod bottom sits here (height above the floor)
pocket = 4.0                       # how deep the pod sits in the cup
r_in = POD_D / 2 + CLEAR
r_out = r_in + WALL
cup_bot = seat_z - BUMP_H - 1.5    # floor under the bump recess
rear = cyl(seat_z + pocket - cup_bot, r_out, z=cup_bot)
rear -= cyl(pocket + 1, r_in, z=seat_z)                                         # pod pocket
rear -= box(0, r_out + 1, -(ARM_W / 2 + CLEAR), ARM_W / 2 + CLEAR, seat_z, seat_z + pocket + 1)  # arm exits +x
rear -= box(-(BUMP_L / 2 + 0.6), BUMP_L / 2 + 0.6, -(BUMP_W / 2 + 0.6), BUMP_W / 2 + 0.6,
            seat_z - BUMP_H - 0.5, seat_z + 0.1)                                # bump recess
for s in (-1, 1):                                                               # strap ears (velcro / zip tie)
    top = box(-4, 4, min(s * (r_out - 1), s * (r_out + 5)), max(s * (r_out - 1), s * (r_out + 5)), seat_z - 2, seat_z + 1)
    zl = cup_bot - 6.0                            # anchor point ON the cone under the cup (no floating start)
    rl = r_out - (cup_bot - zl) - 1.0
    low = box(-3, 3, min(s * (rl - 0.5), s * rl), max(s * (rl - 0.5), s * rl), zl, zl + 0.1)
    ear = (top + low).hull()                      # 45-ish brace under the ear: prints without supports
    slot = box(-3, 3, min(s * (r_out + 1), s * (r_out + 3.5)), max(s * (r_out + 1), s * (r_out + 3.5)),
               seat_z - 3, seat_z + 2)
    rear = rear + ear - slot
cone_h = r_out - 6.5                                                            # 45 deg cone under the cup
rear += cyl(cone_h + 0.01, 6.5, r_out, z=cup_bot - cone_h)
rear += cyl(cup_bot - cone_h + 0.02, 5.0, 6.5)                                  # leg (tapers up)
rear += cyl(1.6, FOOT_D / 2)                                                    # foot pad

# ---- front leg extension: sleeve on a post --------------------------------------------------------
sw, st = TIP_W + 2 * CLEAR, TIP_T + 2 * CLEAR
front = box(-sw / 2 - WALL, sw / 2 + WALL, -st / 2 - WALL, st / 2 + WALL, LIFT - 1.5, LIFT + SOCK_D)
front -= box(-sw / 2, sw / 2, -st / 2, st / 2, LIFT, LIFT + SOCK_D + 1)          # socket for the leg tip
sock_r = ((sw / 2 + WALL) ** 2 + (st / 2 + WALL) ** 2) ** 0.5
front += cyl(sock_r - 5.5 + 0.01, 5.5, sock_r, z=LIFT - 1.5 - (sock_r - 5.5))   # cone under the socket
front += cyl(LIFT - 1.5 - (sock_r - 5.5) + 0.02, 4.5, 5.5)                      # post
front += cyl(1.6, FOOT_D / 2)                                                    # foot pad

here = os.path.dirname(os.path.abspath(__file__))
tr = export(rear, "rear_stand.stl")
tf = export(front, "front_leg_extension.stl")
print(f"rear: pod seat {seat_z:.1f} mm above floor (was {POD_FLOOR:.1f}) | front: leg tip {LIFT:.1f} mm higher")
print(f"belly 'teeth' end up {LIFT:.0f} mm off the floor")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(10, 5))
    for i, (tm, title) in enumerate(((tr, "rear stand (x2)"), (tf, "front leg extension (x2)"))):
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.add_collection3d(Poly3DCollection(tm.vertices[tm.faces], facecolor="#8fb3d9", edgecolor="#2b4a6b", linewidths=0.1))
        mn, mx = tm.bounds; span = (mx - mn).max(); c = (mx + mn) / 2
        for setlim, k in ((ax.set_xlim, 0), (ax.set_ylim, 1), (ax.set_zlim, 2)):
            setlim(c[k] - span / 2, c[k] + span / 2)
        ax.view_init(22, -55); ax.set_title(title); ax.set_axis_off()
    plt.tight_layout(); plt.savefig(os.path.join(here, "stands_preview.png"), dpi=120)
    print("wrote preview cad/stands_preview.png")
except Exception as e:
    print("preview skipped:", e)
