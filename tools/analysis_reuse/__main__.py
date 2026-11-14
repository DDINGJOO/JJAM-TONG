import argparse
import json
from pathlib import Path
from .reuse import AnalysisRequest, execute


def main():
    parser = argparse.ArgumentParser(description="Reuse exact complete local Java analyses", allow_abbrev=False)
    for name in ("tenant", "cache", "source-root", "artifact", "metadata", "module", "java-home", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--include-package", default="fixture.board")
    parser.add_argument("--entrypoint", default="fixture.board.Main")
    parser.add_argument("--artifact-format", choices=("plain", "spring-boot"), default="plain")
    parser.add_argument("--entrypoint-policy", choices=("main", "all-included-methods"), default="main")
    parser.add_argument("--exclude-package", action="append", dest="exclude_packages")
    args = parser.parse_args()
    request = AnalysisRequest(args.tenant, Path(args.source_root), Path(args.artifact), Path(args.metadata), args.module,
                              Path(args.java_home), args.include_package, args.entrypoint, args.artifact_format,
                              args.entrypoint_policy, tuple(args.exclude_packages or ("fixture.board.excluded",)))
    print(json.dumps(execute(request, Path(args.cache), Path(args.output)), sort_keys=True))


if __name__ == "__main__":
    main()
