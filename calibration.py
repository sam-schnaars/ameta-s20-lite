"""Measured flight rates used to turn distances into timed stick pushes.
Fill each from a test flight: fly the move for a known time at REF_SPEED, measure, divide.
None = not calibrated yet -> distance commands for that axis are refused (time commands still work)."""

REF_SPEED = 0.2          # stick fraction used for every calibrated move

PITCH_M_PER_S = None     # forward/back metres per second at REF_SPEED (calibrate.py pitch)
ROLL_M_PER_S = None      # sideways metres per second at REF_SPEED   (calibrate.py roll)
THROTTLE_M_PER_S = None  # vertical metres per second at REF_SPEED   (calibrate.py up)
YAW_DEG_PER_S = None     # degrees per second at REF_SPEED           (calibrate.py yaw)

TAKEOFF_HEIGHT_M = 1.2   # app text for one-key takeoff
MIN_HEIGHT_M = 0.5       # route refuses "down" moves estimated to go below this
MAX_HEIGHT_M = 3.0       # ...and "up" moves estimated to go above this
