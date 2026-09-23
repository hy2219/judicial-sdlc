"""Resolve accepted source after main CI; never start agents or execute PR code."""

import argparse
import json
import os
from pathlib import Path
import sys

from approved_pr import (
    ApprovalError, GitHub, commit_parents, paginated, require_sha, resolve,
    select_plan, snapshot,
)


def handle(api, run_id):
    repo = api.get("")
    if repo.get("private") is not True or repo.get("is_template"):
        raise ApprovalError("Only private scenario repositories produce request installers.")
    run = api.get(f"/actions/runs/{run_id}")
    if (
        run.get("event") != "push" or run.get("name") != "CI"
        or run.get("path") != ".github/workflows/ci.yml" or run.get("status") != "completed"
        or run.get("head_repository", {}).get("full_name") != api.repository
        or run.get("head_branch") != repo["default_branch"]
    ):
        return {}
    source = require_sha(run["head_sha"])
    pulls = paginated(api, f"/commits/{source}/pulls")
    candidates = [pr for pr in pulls if pr.get("merged_at")
                  and pr.get("merge_commit_sha") == source
                  and pr["base"]["ref"] == repo["default_branch"]]
    if not candidates:
        return {}
    if len(candidates) != 1:
        raise ApprovalError("Could not identify one accepted request PR.")
    number = candidates[0]["number"]
    pr = api.get(f"/pulls/{number}")
    parent = commit_parents(api, source, {1})[0]
    plan = select_plan(snapshot(api, parent), snapshot(api, source), request_body=pr.get("body"))
    issue = int(Path(plan).stem)
    result = {"issue": issue, "pr": number, "source": source, "stage": "blocked"}
    if run["conclusion"] != "success":
        print("Main source CI did not succeed; no installer will be built.", file=sys.stderr)
        return result
    try:
        record = resolve(api, issue, number, source)
    except ApprovalError as exc:
        print(f"Merged source blocked: {exc}", file=sys.stderr)
        return result
    return {**result, "stage": "build", "approval": json.dumps(record, separators=(",", ":"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, required=True)
    args = parser.parse_args()
    try:
        event = json.loads(args.event.read_text(encoding="utf-8"))
        api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        result = handle(api, event["workflow_run"]["id"])
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")
        return 1 if result.get("stage") == "blocked" else 0
    except (ApprovalError, OSError, ValueError, KeyError) as exc:
        print(f"Build preparation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
