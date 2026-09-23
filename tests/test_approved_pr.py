import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
from approved_pr import (
    ApprovalError, GitHub, paginated, require_ci, resolve, select_plan, tree_entries,
    validate_scope,
)

BASE, HEAD, SOURCE, PLAN_BLOB = (letter * 40 for letter in "abcd")
REPO = "example/synthetic-demo"


def tree(files):
    return {"truncated": False, "tree": [
        {"path": name, "sha": sha, "mode": "100644", "type": "blob"} for name, sha in files.items()
    ]}


class FakeGitHub(GitHub):
    repository = REPO

    def __init__(self):
        base = {"app/gui.py": "1" * 40, "modules/ocr/__init__.py": "2" * 40}
        head = {**base, "app/gui.py": "3" * 40, "plans/1.json": PLAN_BLOB}
        self.responses = {
            "": {"private": True, "is_template": False, "default_branch": "main"},
            "/issues/1": {"number": 1, "state": "open"},
            "/pulls/2": {
                "number": 2, "state": "closed", "draft": False,
                "merged_at": "2026-09-24T12:00:00Z", "merge_commit_sha": SOURCE,
                "merged_by": {"type": "User", "login": "maintainer"},
                "head": {"repo": {"full_name": REPO}, "ref": "copilot/request", "sha": HEAD},
                "base": {"repo": {"full_name": REPO}, "ref": "main", "sha": BASE},
            },
            "/collaborators/maintainer/permission": {"permission": "write"},
            "/collaborators/reviewer/permission": {"permission": "maintain"},
            "/pulls/2/reviews?per_page=100&page=1": [],
            f"/commits/{SOURCE}": {"sha": SOURCE, "parents": [{"sha": BASE}]},
            f"/git/trees/{BASE}?recursive=1": tree(base),
            f"/git/trees/{HEAD}?recursive=1": tree(head),
            f"/git/trees/{SOURCE}?recursive=1": tree(head),
            f"/git/blobs/{PLAN_BLOB}": {
                "sha": PLAN_BLOB, "encoding": "base64",
                "content": base64.b64encode(b'{"issue":1,"input_preparation":"synthetic"}').decode(),
            },
            f"/commits/{HEAD}/check-runs?per_page=100": {
                "total_count": 1, "check_runs": [{
                    "id": 1, "name": "test", "head_sha": HEAD, "app": {"slug": "github-actions"},
                    "status": "completed", "conclusion": "success",
                }],
            },
        }

    def get(self, path):
        return copy.deepcopy(self.responses[path])

    def files(self, sha):
        return self.responses[f"/git/trees/{sha}?recursive=1"]["tree"]

    def candidate(self, files):
        for sha in (HEAD, SOURCE):
            self.responses[f"/git/trees/{sha}?recursive=1"]["tree"] = copy.deepcopy(files)


class ApprovedPRTests(unittest.TestCase):
    def test_same_pr_squash_record_is_honest_about_plan_comment(self):
        self.assertEqual(resolve(FakeGitHub(), 1, 2, SOURCE), {
            "repository": REPO, "issue": 1, "pull_request": 2, "plan_path": "plans/1.json",
            "request_kind": "initial",
            "plan_blob_sha": PLAN_BLOB, "base_sha": BASE,
            "implementation_head_sha": HEAD, "head_sha": SOURCE, "source_commit": SOURCE,
            "implementation_merged_by": "maintainer", "merged_to_default_branch": True,
            "merge_method": "squash", "plan_approval": "manual_pr_comment_not_machine_verified",
            "changed_files": ["app/gui.py", "plans/1.json"],
        })

    def test_plan_only_passes_scope_but_does_not_build(self):
        api = FakeGitHub()
        base = tree_entries(api.responses[f"/git/trees/{BASE}?recursive=1"])
        plan = {**base, "plans/1.json": ("100644", PLAN_BLOB)}
        self.assertEqual(validate_scope(base, plan), ("plans/1.json", ["plans/1.json"]))
        with self.assertRaisesRegex(ApprovalError, "no application"):
            validate_scope(base, plan, require_implementation=True)
        api.candidate(tree({name: value[1] for name, value in plan.items()})["tree"])
        with self.assertRaisesRegex(ApprovalError, "no application"):
            resolve(api, 1, 2, SOURCE)

    def test_shared_sources_and_unrelated_plans_are_rejected(self):
        for path in (".github/workflows/rogue.yml", "modules/ocr/engine.py", "requirements.txt",
                     "packaging/windows-installer.iss", "tests/ocr_check.py", "run.py", "plans/2.json"):
            api = FakeGitHub()
            api.candidate([*api.files(HEAD), {"path": path, "sha": "e" * 40, "mode": "100644", "type": "blob"}])
            with self.subTest(path=path), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)

    def test_initial_plan_cannot_be_missing_or_overwrite_previous_issue(self):
        for change in ("missing", "previous"):
            api = FakeGitHub()
            if change == "missing":
                api.candidate([file for file in api.files(HEAD) if file["path"] != "plans/1.json"])
            else:
                api.files(BASE).append({"path": "plans/1.json", "sha": "e" * 40, "mode": "100644", "type": "blob"})
            with self.subTest(change=change), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)

    def test_follow_up_reuses_unchanged_plan_for_app_or_test_only_fix(self):
        for path in ("app/gui.py", "tests/test_app.py"):
            api = FakeGitHub()
            base = tree({
                "app/gui.py": "1" * 40, "modules/ocr/__init__.py": "2" * 40,
                "plans/1.json": PLAN_BLOB,
            })["tree"]
            api.responses[f"/git/trees/{BASE}?recursive=1"]["tree"] = base
            candidate = {entry["path"]: entry["sha"] for entry in base}
            candidate[path] = "e" * 40
            api.candidate(tree(candidate)["tree"])
            record = resolve(api, 1, 2, SOURCE)
            self.assertEqual(record["request_kind"], "follow_up")
            self.assertEqual(record["plan_blob_sha"], PLAN_BLOB)
            self.assertEqual(record["changed_files"], [path])

    def test_follow_up_never_edits_or_deletes_plans_or_shared_source(self):
        base = {
            "app/gui.py": ("100644", "1" * 40),
            "plans/1.json": ("100644", PLAN_BLOB),
            "modules/ocr/engine.py": ("100644", "2" * 40),
        }
        for mode in ("delete", "edit", "shared", "empty"):
            candidate = dict(base)
            if mode != "empty":
                candidate["app/gui.py"] = ("100644", "3" * 40)
            if mode == "delete":
                del candidate["plans/1.json"]
            elif mode == "edit":
                candidate["plans/1.json"] = ("100644", "e" * 40)
            elif mode == "shared":
                candidate["modules/ocr/engine.py"] = ("100644", "e" * 40)
            with self.subTest(mode=mode), self.assertRaises(ApprovalError):
                validate_scope(base, candidate, require_implementation=True)

    def test_multiple_plans_require_an_explicit_existing_reference(self):
        base = {"plans/1.json": ("100644", PLAN_BLOB), "plans/4.json": ("100644", "e" * 40)}
        candidate = {**base, "tests/test_app.py": ("100644", "f" * 40)}
        for body in ("", "Refs #9", "Refs #1\nRefs #4", "Fixes #1"):
            with self.subTest(body=body), self.assertRaises(ApprovalError):
                select_plan(base, candidate, request_body=body)
        self.assertEqual(validate_scope(base, candidate, request_body="Repair\n\nRefs #4\n"),
                         ("plans/4.json", ["tests/test_app.py"]))

    def test_follow_up_keeps_real_issue_and_human_merge_ci_checks(self):
        for mode in ("issue", "human", "ci", "source"):
            api = FakeGitHub()
            api.files(BASE).append({"path": "plans/1.json", "mode": "100644",
                                    "type": "blob", "sha": PLAN_BLOB})
            if mode == "issue":
                api.responses["/issues/1"]["pull_request"] = {}
            elif mode == "human":
                api.responses["/pulls/2"]["merged_by"]["type"] = "Bot"
            elif mode == "ci":
                api.responses[f"/commits/{HEAD}/check-runs?per_page=100"]["check_runs"][0]["conclusion"] = "failure"
            else:
                api.files(SOURCE)[0]["sha"] = "f" * 40
            with self.subTest(mode=mode), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)

    def test_pr_reference_change_during_resolution_blocks(self):
        api = FakeGitHub()
        get, count = api.get, 0
        def changed(path):
            nonlocal count
            result = get(path)
            if path == "/pulls/2":
                count += 1
                result["body"] = "Refs #1" if count == 1 else "Refs #4"
            return result
        api.get = changed
        with self.assertRaisesRegex(ApprovalError, "changed"):
            resolve(api, 1, 2, SOURCE)

    def test_plan_json_and_issue_must_match(self):
        for document in ([], {}, {"issue": 2}, {"issue": True}):
            api = FakeGitHub()
            api.responses[f"/git/blobs/{PLAN_BLOB}"]["content"] = base64.b64encode(json.dumps(document).encode()).decode()
            with self.subTest(document=document), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)
        api = FakeGitHub()
        api.responses["/issues/1"]["pull_request"] = {}
        with self.assertRaisesRegex(ApprovalError, "not a PR"):
            resolve(api, 1, 2, SOURCE)

    def test_malformed_plan_blob_fails(self):
        for field, value in (("content", "!bad"), ("encoding", "utf8"), ("sha", "e" * 40)):
            api = FakeGitHub()
            api.responses[f"/git/blobs/{PLAN_BLOB}"][field] = value
            with self.subTest(field=field), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)

    def test_only_human_write_role_merged_pr_builds(self):
        for merger in ({}, {"type": "Bot", "login": "maintainer"}):
            api = FakeGitHub()
            api.responses["/pulls/2"]["merged_by"] = merger
            with self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)
        for role in ("read", "none"):
            api = FakeGitHub()
            api.responses["/collaborators/maintainer/permission"]["permission"] = role
            with self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)
        for key, value in (("state", "open"), ("draft", True), ("merged_at", None)):
            api = FakeGitHub()
            api.responses["/pulls/2"][key] = value
            with self.subTest(key=key), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)

    def test_wrong_repo_branch_or_public_source_is_rejected(self):
        for section, field, value in (("head", "ref", "main"), ("base", "ref", "task/issue-1")):
            api = FakeGitHub()
            api.responses["/pulls/2"][section][field] = value
            with self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)
        api = FakeGitHub()
        api.responses["/pulls/2"]["head"]["repo"]["full_name"] = "other/fork"
        with self.assertRaises(ApprovalError):
            resolve(api, 1, 2, SOURCE)
        api = FakeGitHub()
        api.responses[""]["private"] = False
        with self.assertRaises(ApprovalError):
            resolve(api, 1, 2, SOURCE)

    def test_actual_squash_source_must_match_head_tree_and_single_parent(self):
        for mutation in ("parents", "tree", "sha"):
            api = FakeGitHub()
            if mutation == "parents":
                api.responses[f"/commits/{SOURCE}"]["parents"].append({"sha": HEAD})
            elif mutation == "tree":
                api.files(SOURCE)[0]["sha"] = "e" * 40
            else:
                api.responses["/pulls/2"]["merge_commit_sha"] = "e" * 40
            with self.subTest(mutation=mutation), self.assertRaises(ApprovalError):
                resolve(api, 1, 2, SOURCE)

    def test_outstanding_changes_request_blocks_and_dismissal_clears(self):
        api = FakeGitHub()
        api.responses["/pulls/2/reviews?per_page=100&page=1"] = [
            {"id": 1, "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"},
        ]
        with self.assertRaisesRegex(ApprovalError, "changes request"):
            resolve(api, 1, 2, SOURCE)
        api.responses["/pulls/2/reviews?per_page=100&page=1"].append(
            {"id": 2, "user": {"login": "reviewer"}, "state": "DISMISSED"},
        )
        resolve(api, 1, 2, SOURCE)

    def test_missing_failed_or_newer_pending_source_ci_blocks(self):
        for state in ("missing", "failure", "pending", "wrong_head", "too_many"):
            api = FakeGitHub()
            checks = api.responses[f"/commits/{HEAD}/check-runs?per_page=100"]
            if state == "missing":
                checks.update(total_count=0, check_runs=[])
            elif state == "failure":
                checks["check_runs"][0]["conclusion"] = "failure"
            elif state == "wrong_head":
                checks["check_runs"][0]["head_sha"] = BASE
            elif state == "too_many":
                checks["total_count"] = 101
            else:
                checks["check_runs"].append({**checks["check_runs"][0], "id": 2,
                                            "status": "in_progress", "conclusion": None})
                checks["total_count"] = 2
            with self.subTest(state=state), self.assertRaises(ApprovalError):
                require_ci(api, HEAD)

    def test_unsafe_or_truncated_tree_fails(self):
        for value in ({"truncated": True, "tree": []}, tree({"../escape.py": HEAD}),
                      {"truncated": False, "tree": [{"path": "x", "mode": "120000", "type": "blob", "sha": HEAD}]}):
            with self.assertRaises(ApprovalError):
                tree_entries(value)

    def test_recheck_catches_head_changes(self):
        api = FakeGitHub()
        get, count = api.get, 0
        def changed(path):
            nonlocal count
            result = get(path)
            if path == "/pulls/2":
                count += 1
                if count == 2:
                    result["head"]["sha"] = BASE
            return result
        api.get = changed
        with self.assertRaisesRegex(ApprovalError, "changed"):
            resolve(api, 1, 2, SOURCE)

    def test_pagination_never_silently_truncates(self):
        api = GitHub(REPO, "synthetic")
        with patch.object(api, "get", side_effect=[[{}] * 100, [{}]]):
            self.assertEqual(len(paginated(api, "/pulls")), 101)
        with patch.object(api, "get", return_value=[{}] * 100):
            with self.assertRaisesRegex(ApprovalError, "Pagination"):
                paginated(api, "/pulls")


if __name__ == "__main__":
    unittest.main()
