"""A finite one-shot worker; no daemon or external broker required."""
import argparse
import json
import os
import time
from .adapters import LocalGit, GitHub, settings
from .reconcile import Store, work


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--git")
    parser.add_argument("--repository", default="fixture/community")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--prefix", action="append")
    parser.add_argument("--now", type=float)
    parser.add_argument("--crash", choices=("after_claim", "during_publish"))
    args = parser.parse_args()
    config = settings(args.prefix or ("services/",))
    source = (LocalGit(args.git, args.repository, "refs/heads/" + args.ref, config) if args.git
              else GitHub(args.repository, args.ref, config, token=os.environ.get("JJAMTONG_GITHUB_TOKEN")))
    now = time.time() if args.now is None else args.now
    store = Store(args.database, source.source, config)
    try:
        if args.crash == "after_claim":
            if store.claim(now):
                os._exit(17)
            raise RuntimeError("no work claimed")
        fault = (lambda: os._exit(17)) if args.crash == "during_publish" else None
        result = work(store, source, now, fault, time.time if args.now is None else None)
        print(json.dumps(result, sort_keys=True))
    finally:
        store.close()


if __name__ == "__main__":
    main()
