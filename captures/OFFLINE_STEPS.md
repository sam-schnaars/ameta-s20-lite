# Offline capture steps (props OFF, drone on a table, Mac joined to drone Wi-Fi)

Open Terminal and:  cd ~/Gabriel/ameta_s20/captures

## 0. Record the network (no sudo)
  (ifconfig en0 | grep "inet "; netstat -rn | grep default) | tee 00_network.txt

## 1. For each experiment: run the command, THEN do the action in the app
Each capture lasts 30 s. Start the command first, wait ~3 s, then act at about the 10 s mark.
Between captures: put the app back to a resting state (landed, sticks centered).

| #  | command                          | what to do in the app                                  |
|----|----------------------------------|--------------------------------------------------------|
| 01 | sudo ./cap.sh 01_idle 30         | Open app, tap connect, then touch NOTHING              |
| 02 | sudo ./cap.sh 02_takeoff 30      | Tap takeoff ONCE at ~10 s, leave it                    |
| 03 | sudo ./cap.sh 03_land 30         | (after takeoff) tap land ONCE at ~10 s                 |
| 04 | sudo ./cap.sh 04_pitch_fwd 30    | Push ONLY the forward stick, hold ~3 s, release        |
| 05 | sudo ./cap.sh 05_pitch_back 30   | Same, backward                                         |
| 06 | sudo ./cap.sh 06_roll_right 30   | Same, right                                            |
| 07 | sudo ./cap.sh 07_roll_left 30    | Same, left                                             |
| 08 | sudo ./cap.sh 08_yaw_right 30    | Rotate right only, hold ~3 s                           |
| 09 | sudo ./cap.sh 09_throttle_up 30  | Throttle up only, hold ~3 s                            |
| 10 | sudo ./cap.sh 10_throttle_down 30| Throttle down only, hold ~3 s                          |

Props stay off for all of these. Keep hands/face clear: motors may spin on takeoff.
Skip any step the app refuses. Note the exact time you did the action in each (e.g. "tapped at ~10 s").
Optional: 11_trajectory (draw a short path, start it).

## 2. When finished
Rejoin your normal Wi-Fi, then tell Claude. Files are in this folder.
If the app says "can't connect" at step 01, note the message and tell Claude.
