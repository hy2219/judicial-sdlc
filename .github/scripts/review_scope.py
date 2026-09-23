"""Read-only pre-merge scope check; do not import or execute PR source."""

import json
import os
from pathlib import Path
import sys

from approved_pr import ApprovalError, GitHub, check_pr, read_plan, snapshot, validate_scope


def check_scope(api, number, expected_head=None):
    repo = api.get("")
    pr = api.get(f"/pulls/{number}")
    if expected_head is not None and pr["head"]["sha"] != expected_head:
        raise ApprovalError("PR head no longer matches this event; wait for the new head check.")
    default = repo["default_branch"]
    check_pr(pr, api.repository, default, {default})
    base, head = snapshot(api, pr["base"]["sha"]), snapshot(api, pr["head"]["sha"])
    path, _ = validate_scope(base, head, request_body=pr.get("body"))
    read_plan(api, head[path][1], int(Path(path).stem))
    stable_pr(api, pr)


def stable_pr(api, before):
    after = api.get(f"/pulls/{before['number']}")
    if (before["head"]["sha"], before["base"]["sha"], before["base"]["ref"], before.get("body")) != (
        after["head"]["sha"], after["base"]["sha"], after["base"]["ref"], after.get("body"),
    ):
        raise ApprovalError("PR head/base changed during the scope check.")


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    try:
        api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        check_scope(api, event["number"], event["pull_request"]["head"]["sha"])
    except (ApprovalError, OSError, ValueError, KeyError) as exc:
        print(f"PR scope blocked: {exc}", file=sys.stderr)
        return 2
    print("PR source scope matches the request phase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
