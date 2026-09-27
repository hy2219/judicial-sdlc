"""Read-only scope and provenance checks for initial and follow-up request PRs."""

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SHA = re.compile(r"[0-9a-f]{40}")
APP_PATH = re.compile(r"app/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py")
PLAN_PATH = re.compile(r"plans/[1-9][0-9]*\.json")
WRITE_ROLES = {"write", "maintain", "admin"}


class ApprovalError(ValueError):
    pass


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise ApprovalError("Repository and a read-only token are required.")
        self.repository = repository
        self.token = token

    def get(self, suffix):
        req = Request(
            f"https://api.github.com/repos/{self.repository}{suffix}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(req, timeout=30) as response:
                raw = response.read(10_000_001)
        except HTTPError as exc:
            exc.close()
            raise ApprovalError(f"GitHub could not verify approval (HTTP {exc.code}).") from exc
        except (URLError, OSError) as exc:
            raise ApprovalError("GitHub approval lookup failed; no source is approved.") from exc
        if len(raw) > 10_000_000:
            raise ApprovalError("Approval response exceeded the size limit.")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ApprovalError("Invalid GitHub JSON response.") from exc

    def reviews(self, number):
        return paginated(self, f"/pulls/{number}/reviews")


def paginated(api, path, parameters=None):
    results = []
    for page in range(1, 11):
        query = urlencode({**(parameters or {}), "per_page": 100, "page": page})
        items = api.get(f"{path}?{query}")
        if not isinstance(items, list) or len(items) > 100:
            raise ApprovalError("Invalid paginated GitHub response.")
        results.extend(items)
        if len(items) < 100:
            return results
    raise ApprovalError("Pagination limit reached; cannot verify all results.")


def require_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ApprovalError("Full lowercase 40-character commit/blob SHAs are required.")
    return value


def require_number(value):
    if type(value) is not int or value <= 0:
        raise ApprovalError("Positive integer issue and PR numbers are required.")


def default_branch(api):
    repo = api.get("")
    default = repo.get("default_branch")
    if repo.get("private") is not True or not isinstance(default, str) or not default:
        raise ApprovalError("A private repository with a default branch is required.")
    return default


def require_ci(api, head):
    require_sha(head)
    checks = api.get(f"/commits/{head}/check-runs?per_page=100")
    count, runs = checks.get("total_count"), checks.get("check_runs")
    if type(count) is not int or not 0 <= count <= 100 or not isinstance(runs, list) or len(runs) != count:
        raise ApprovalError("Cannot verify complete CI checks within the 100-check limit.")
    for name in ("test", "e2e"):
        source = [
            check for check in runs
            if check.get("name") == name and (check.get("app") or {}).get("slug") == "github-actions"
        ]
        if any(type(check.get("id")) is not int for check in source):
            raise ApprovalError("Invalid source CI check identifier.")
        latest = max(source, key=lambda check: check["id"]) if source else {}
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ApprovalError(f"The exact head needs a successful latest source CI '{name}' check.")
        if latest.get("head_sha") != head:
            raise ApprovalError("Source CI check does not match the exact head.")


def check_pr(pr, repository, default, bases):
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if (
        (head.get("repo") or {}).get("full_name") != repository
        or (base.get("repo") or {}).get("full_name") != repository
        or base.get("ref") not in bases or not head.get("ref")
        or head["ref"] in {default, base.get("ref")}
    ):
        raise ApprovalError("PR must use a same-repository non-default head and the expected base.")
    return require_sha(head.get("sha"))


def merged_pr(api, number, base_branch):
    require_number(number)
    pr = api.get(f"/pulls/{number}")
    check_pr(pr, api.repository, default_branch(api), {base_branch})
    if pr.get("number") != number or pr.get("state") != "closed" or not pr.get("merged_at") or pr.get("draft") is not False:
        raise ApprovalError("PR must be closed, merged and not a draft.")
    require_sha(pr.get("merge_commit_sha"))
    merger = pr.get("merged_by") or {}
    if merger.get("type") != "User" or not merger.get("login"):
        raise ApprovalError("A human with repository write access must perform the merge.")
    permissions = {}

    def permission(login):
        if login not in permissions:
            permissions[login] = api.get(
                "/collaborators/" + quote(login, safe="") + "/permission"
            ).get("permission")
        return permissions[login]

    if permission(merger["login"]) not in WRITE_ROLES:
        raise ApprovalError("The human merger needs repository write, maintain or admin access.")
    latest = {}
    for review in sorted(api.reviews(number), key=lambda item: item["id"]):
        user = review.get("user") or {}
        if user.get("login") and review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[user["login"]] = review
    for login, review in latest.items():
        if review["state"] == "CHANGES_REQUESTED" and permission(login) in WRITE_ROLES:
            raise ApprovalError("A write-role reviewer has an outstanding changes request.")
    return pr


def tree_entries(tree):
    if tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
        raise ApprovalError("Complete Git tree could not be verified.")
    entries, seen = {}, set()
    for item in tree["tree"]:
        name = item.get("path", "")
        if (
            not isinstance(name, str) or not name or name.startswith("/") or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/")) or name in seen
        ):
            raise ApprovalError("Unsafe or duplicate path in candidate snapshot.")
        seen.add(name)
        require_sha(item.get("sha"))
        if item.get("type") == "tree" and item.get("mode") == "040000":
            continue
        if item.get("type") != "blob" or item.get("mode") not in {"100644", "100755"}:
            raise ApprovalError("Unsafe file, symlink or submodule in candidate snapshot.")
        entries[name] = (item["mode"], item["sha"])
    return entries


def changed_paths(base, head):
    return {name for name in set(base) | set(head) if base.get(name) != head.get(name)}


def select_plan(base, candidate, *, request_body=""):
    actual = changed_paths(base, candidate)
    plans = [path for path in actual if path.startswith("plans/")]
    if plans:
        if len(plans) != 1:
            raise ApprovalError("A new request must add exactly one plan JSON file.")
        plan_path = plans[0]
        if not PLAN_PATH.fullmatch(plan_path) or plan_path in base or plan_path not in candidate:
            raise ApprovalError("Existing plans must remain unchanged; add a new plan only for a new request.")
        return plan_path
    existing = [path for path in base if PLAN_PATH.fullmatch(path)]
    references = set(re.findall(r"^Refs #([1-9][0-9]*)\s*$", request_body or "", re.MULTILINE))
    if references:
        if len(references) != 1:
            raise ApprovalError("A follow-up PR must reference exactly one existing request with Refs #N.")
        plan_path = f"plans/{next(iter(references))}.json"
        if plan_path not in existing:
            raise ApprovalError("The referenced request has no existing plan in the base branch.")
        return plan_path
    if len(existing) != 1:
        raise ApprovalError("A first request needs a plan; with multiple existing plans, specify Refs #N in the PR body.")
    return existing[0]


def validate_scope(base, candidate, *, require_implementation=False, request_body=""):
    actual = changed_paths(base, candidate)
    plan_path = select_plan(base, candidate, request_body=request_body)
    blocked = [
        name for name in actual
        if not (APP_PATH.fullmatch(name) or name == "tests/test_app.py" or name == plan_path)
    ]
    if blocked:
        raise ApprovalError("Tasks cannot change shared modules, workflows, packaging, scripts or dependencies: "
                            + ", ".join(sorted(blocked)))
    if not actual:
        raise ApprovalError("A request PR must contain source or new-plan changes.")
    if require_implementation and actual <= {plan_path}:
        raise ApprovalError("Implementation PR has no application changes.")
    return plan_path, sorted(actual)


def snapshot(api, sha):
    return tree_entries(api.get(f"/git/trees/{require_sha(sha)}?recursive=1"))


def commit_parents(api, sha, allowed):
    commit = api.get("/commits/" + require_sha(sha))
    parents = commit.get("parents")
    if commit.get("sha") != sha or not isinstance(parents, list) or len(parents) not in allowed:
        raise ApprovalError("Commit identity or merge parent count is invalid.")
    return [require_sha(parent.get("sha")) for parent in parents]


def unchanged_pr(before, after):
    fields = lambda pr: (pr["head"]["sha"], pr["head"]["ref"], pr["base"]["ref"],
                         pr.get("merge_commit_sha"), pr.get("merged_by"), pr.get("merged_at"),
                         pr.get("body"))
    if fields(before) != fields(after):
        raise ApprovalError("PR head or merge identity changed during validation; retry.")


def read_plan(api, blob_sha, issue_number):
    blob = api.get("/git/blobs/" + blob_sha)
    if blob.get("sha") != blob_sha or blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
        raise ApprovalError("The plan must be a verifiable base64 JSON blob.")
    try:
        content = base64.b64decode("".join(blob["content"].splitlines()), validate=True).decode("utf-8")
        document = json.loads(content)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ApprovalError("The plan must contain valid base64 UTF-8 JSON.") from exc
    if not isinstance(document, dict) or type(document.get("issue")) is not int or document["issue"] != issue_number:
        raise ApprovalError("The plan JSON must identify this exact issue.")
    issue = api.get(f"/issues/{issue_number}")
    if issue.get("number") != issue_number or "pull_request" in issue:
        raise ApprovalError("The plan must refer to an existing requirement Issue, not a PR.")
    return document


def resolve(api, issue_number, implementation_number, source_sha):
    require_number(issue_number)
    require_number(implementation_number)
    require_sha(source_sha)
    default = default_branch(api)
    pr = merged_pr(api, implementation_number, default)
    head = pr["head"]["sha"]
    if pr["merge_commit_sha"] != source_sha:
        raise ApprovalError("Source SHA must match the implementation PR's actual merge commit.")
    parent = commit_parents(api, source_sha, {1})[0]
    candidate = snapshot(api, head)
    if snapshot(api, source_sha) != candidate:
        raise ApprovalError("Squash merge tree must exactly match the implementation PR head tree.")
    base = snapshot(api, parent)
    plan_path, changes = validate_scope(
        base, candidate, require_implementation=True, request_body=pr.get("body"),
    )
    if plan_path != f"plans/{issue_number}.json":
        raise ApprovalError("Plan path does not match the request Issue.")
    plan_blob = candidate[plan_path][1]
    read_plan(api, plan_blob, issue_number)
    require_ci(api, head)
    unchanged_pr(pr, merged_pr(api, implementation_number, default))
    return {
        "repository": api.repository, "issue": issue_number, "pull_request": implementation_number,
        "request_kind": "follow_up" if plan_path in base else "initial",
        "plan_path": plan_path, "plan_blob_sha": plan_blob, "base_sha": parent,
        "plan_approval": "manual_pr_comment_not_machine_verified",
        "implementation_head_sha": head, "head_sha": source_sha, "source_commit": source_sha,
        "implementation_merged_by": pr["merged_by"]["login"], "merged_to_default_branch": True,
        "merge_method": "squash", "changed_files": changes,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        api = GitHub(os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", ""))
        result = resolve(api, args.issue, args.pr, args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                for key in ("head_sha", "issue", "pull_request"):
                    output.write(f"{key}={result[key]}\n")
    except (ApprovalError, OSError, ValueError, KeyError) as exc:
        print(f"Merged-PR build blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Verified merged PR #{args.pr} at {result['head_sha']}; no remote writes performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
