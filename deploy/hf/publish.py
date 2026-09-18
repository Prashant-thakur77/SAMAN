"""Publish SAMAN as a Hugging Face Space and wait until it runs.

    make space SPACE=<user>/saman            # first time, and after edits here
    make space SPACE=<user>/saman REBUILD=1  # after a push to GitHub

Needs a Hugging Face token with write access: `hf auth login` once, or
HF_TOKEN in the environment. The Space holds only this directory's Dockerfile
and README.md; the build clones the GitHub repository itself. A random
SAMAN_SECRET_KEY is set as a Space secret so sessions are not signed with the
development default.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLL_SECONDS = 20
GIVE_UP_AFTER = 40 * 60


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("space", help="<user>/<name>, for example prashant/saman")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="factory rebuild (drops the build cache, so a new GitHub commit is picked up)",
    )
    parser.add_argument("--no-wait", action="store_true", help="return without polling")
    args = parser.parse_args(argv)

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("huggingface_hub is not installed: pip install huggingface_hub", file=sys.stderr)
        return 2

    api = HfApi()
    try:
        me = api.whoami()["name"]
    except Exception as exc:  # noqa: BLE001 - the message is the point
        print(f"Not signed in to Hugging Face ({exc}). Run `hf auth login` or set HF_TOKEN.")
        return 2
    print(f"signed in as {me}")

    if args.rebuild:
        api.restart_space(args.space, factory_reboot=True)
        print("factory rebuild requested")
    else:
        api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
        api.add_space_secret(args.space, "SAMAN_SECRET_KEY", secrets.token_urlsafe(48))
        api.upload_folder(
            folder_path=str(HERE),
            repo_id=args.space,
            repo_type="space",
            allow_patterns=["Dockerfile", "README.md"],
            commit_message="SAMAN: single-container Space",
        )
        print(f"pushed Dockerfile and README.md to https://huggingface.co/spaces/{args.space}")

    if args.no_wait:
        return 0

    owner, name = args.space.split("/", 1)
    site = f"https://{owner}-{name}.hf.space".lower().replace("_", "-").replace(".", "-")
    started = time.time()
    last = None
    while time.time() - started < GIVE_UP_AFTER:
        runtime = api.get_space_runtime(args.space)
        stage = str(runtime.stage)
        if stage != last:
            print(f"{int(time.time() - started):4d}s  {stage}")
            last = stage
        if stage.endswith("RUNNING"):
            print(f"\nlive at {site}")
            return 0
        if stage.endswith("ERROR"):
            print(f"\nthe Space is in {stage}; open its Logs tab on huggingface.co")
            return 1
        time.sleep(POLL_SECONDS)
    print("still building after 40 minutes; check the Space's Logs tab")
    return 1


if __name__ == "__main__":
    sys.exit(main())
