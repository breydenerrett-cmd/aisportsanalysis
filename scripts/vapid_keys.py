"""Make the Web Push (VAPID) key and put it on the Fly app WITHOUT ever printing it.

    python scripts/vapid_keys.py --app linehound-prod

The private key is generated here, piped straight into ``fly secrets import`` on stdin, and never written to the
screen, a file or a log. Only the PUBLIC key (safe to share; the browser needs it) is printed, so you can check the
site reports the same one. Run it once; running it again REPLACES the key and every browser has to switch
notifications on again. ``--dry-run`` generates and prints only the public key and sets nothing.

Needs the ``cryptography`` package (pip install cryptography) and the ``fly`` CLI signed in.
docs/owner/ALERTS.md has the full steps.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.notify import webpush  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", default="linehound-prod", help="the Fly app name")
    parser.add_argument("--dry-run", action="store_true", help="print the public key only; set nothing")
    args = parser.parse_args(argv)
    private = webpush.generate_private_key()
    public = webpush.public_key({webpush.ENV_PRIVATE: private})
    if not args.dry_run:
        fly = shutil.which("fly") or shutil.which("flyctl")
        if not fly:
            print("The fly CLI was not found. Install it from https://fly.io/docs/flyctl/install/ and sign in.")
            return 2
        done = subprocess.run([fly, "secrets", "import", "--app", args.app],
                              input=f"{webpush.ENV_PRIVATE}={private}\n", text=True, capture_output=True)
        if done.returncode != 0:
            print("fly refused the secret (exit", done.returncode, "). Nothing was changed. Is the app name right and are you signed in?")
            return done.returncode
        print(f"VAPID key set on {args.app}. The app restarts to pick it up.")
    print("Public key (safe to share):", public)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
