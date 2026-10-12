"""Install the ProQ2Bridge FL Studio MIDI script (Windows).

Copies fl_bridge/device_ProQ2Bridge.py into FL Studio's Hardware folder,
then prints the manual FL MIDI Settings steps.

Usage:
    python scripts/install_midi_bridge.py [--port ProQ2Bridge]
"""
import argparse
import os
import shutil
import sys

SRC = os.path.join(os.path.dirname(__file__), "..", "fl_bridge",
                   "device_ProQ2Bridge.py")
SCRIPT_NAME = "device_ProQ2Bridge.py"
SUBDIR = "ProQ2Bridge"


def hardware_dirs(explicit=None):
    """All candidate FL Studio Hardware/ProQ2Bridge dirs.

    The user may have multiple FL versions with separate user-data
    folders (e.g. "FL Studio", "FL Studio 21"). Install into every
    candidate found so the running FL picks it up regardless.
    """
    import glob
    cands = []
    if explicit:
        cands = [explicit]
    else:
        base = os.path.join(os.path.expanduser("~"), "Documents",
                            "Image-Line")
        for d in sorted(glob.glob(os.path.join(base, "FL Studio*"))):
            if os.path.isdir(d):
                cands.append(d)
        if not cands:  # fallback to the standard location
            cands = [os.path.join(base, "FL Studio")]
    return [os.path.join(d, "Settings", "Hardware", SUBDIR) for d in cands]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="ProQ2Bridge",
                    help="dedicated loopMIDI port name for bridge traffic")
    ap.add_argument("--fl-user-data", default=None,
                    help="explicit FL user-data folder (default: auto-detect "
                         "all 'FL Studio*' folders under Documents/Image-Line)")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print("ERROR: FL script not found at %s" % SRC)
        return 1
    installed = []
    for dest_dir in hardware_dirs(args.fl_user_data):
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, SCRIPT_NAME)
        shutil.copy2(SRC, dest)
        installed.append(dest)
    print("installed to %d location(s):" % len(installed))
    for d in installed:
        print("  " + d)
    print()
    print("Next steps (one-time):")
    print("  1. In loopMIDI, create a port named '%s' and keep loopMIDI "
          "running." % args.port)
    print("  2. (Re)start FL Studio > Options > MIDI Settings > Input:")
    print("     enable '%s', set Controller type to 'ProQ2Bridge'."
          % args.port)
    print("  3. In config/agent_config.yaml set midi_bridge.port_name: "
          "'%s' (default already)." % args.port)
    print("  4. Verify: python scripts/dump_eq2_params.py")
    print("     (should find Fruity Parametric EQ 2 and list its params)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
