import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
import merged_build
import review_scope
from tests.test_approved_pr import FakeGitHub, BASE, HEAD, SOURCE, REPO, PLAN_BLOB


def build_api():
    api = FakeGitHub()
    api.responses["/actions/runs/42"] = {
        "event": "push", "name": "CI", "path": ".github/workflows/ci.yml",
        "status": "completed", "conclusion": "success", "head_sha": SOURCE, "head_branch": "main",
        "head_repository": {"full_name": REPO},
    }
    api.responses[f"/commits/{SOURCE}/pulls?per_page=100&page=1"] = [api.responses["/pulls/2"]]
    api.responses["/pulls/2/files?per_page=100&page=1"] = [
        {"filename": "app/gui.py"}, {"filename": "plans/1.json"},
    ]
    return api


class MergedBuildTests(unittest.TestCase):
    def test_one_merged_pr_resolves_exact_source_and_plan_blob(self):
        result = merged_build.handle(build_api(), 42)
        self.assertEqual(result["stage"], "build")
        self.assertEqual(result["issue"], 1)
        self.assertEqual(result["pr"], 2)
        self.assertEqual(result["source"], SOURCE)
        record = json.loads(result["approval"])
        self.assertEqual(record["plan_blob_sha"], PLAN_BLOB)
        self.assertEqual(record["plan_approval"], "manual_pr_comment_not_machine_verified")
        self.assertNotIn("plan_pull_request", record)

    def test_actual_gate_record_is_accepted_by_installer_metadata(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
        from package_metadata import validate_source_approval
        result = merged_build.handle(build_api(), 42)
        record = json.loads(result["approval"])
        self.assertEqual(validate_source_approval(record, SOURCE), record)

    def test_follow_up_without_new_plan_builds_for_original_issue(self):
        api = build_api()
        api.files(BASE).append({"path": "plans/1.json", "mode": "100644",
                                "type": "blob", "sha": PLAN_BLOB})
        api.responses["/issues/1"]["state"] = "closed"
        api.responses["/pulls/2/files?per_page=100&page=1"] = [{"filename": "app/gui.py"}]
        result = merged_build.handle(api, 42)
        record = json.loads(result["approval"])
        self.assertEqual((result["stage"], result["issue"]), ("build", 1))
        self.assertEqual(record["request_kind"], "follow_up")
        self.assertEqual(record["changed_files"], ["app/gui.py"])
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
        from package_metadata import validate_source_approval
        self.assertEqual(validate_source_approval(record, SOURCE), record)

    def test_ambiguous_follow_up_blocks_instead_of_selecting_an_arbitrary_issue(self):
        api = build_api()
        for sha in (BASE, HEAD, SOURCE):
            api.files(sha).append({"path": "plans/4.json", "mode": "100644",
                                   "type": "blob", "sha": "e" * 40})
        api.files(BASE).append({"path": "plans/1.json", "mode": "100644",
                                "type": "blob", "sha": PLAN_BLOB})
        with self.assertRaisesRegex(merged_build.ApprovalError, "multiple existing plans"):
            merged_build.handle(api, 42)
        api.responses["/pulls/2"]["body"] = "Refs #1"
        self.assertEqual(merged_build.handle(api, 42)["stage"], "build")

    def test_follow_up_failed_ci_or_modified_shared_source_still_blocks(self):
        for mode in ("ci", "shared"):
            api = build_api()
            api.files(BASE).append({"path": "plans/1.json", "mode": "100644",
                                    "type": "blob", "sha": PLAN_BLOB})
            if mode == "ci":
                api.responses["/actions/runs/42"]["conclusion"] = "failure"
            else:
                for sha in (HEAD, SOURCE):
                    api.files(sha)[1]["sha"] = "f" * 40
            with self.subTest(mode=mode):
                self.assertEqual(merged_build.handle(api, 42)["stage"], "blocked")

    def test_only_main_same_repo_push_ci_can_build(self):
        for field, value in (("event", "pull_request"), ("name", "Unrelated CI"),
                             ("head_branch", "copilot/request"),
                             ("path", "evil.yml"), ("status", "in_progress"),
                             ("head_repository", {"full_name": "other/fork"})):
            api = build_api()
            api.responses["/actions/runs/42"][field] = value
            with self.subTest(field=field):
                self.assertEqual(merged_build.handle(api, 42), {})

    def test_template_and_public_repo_cannot_build_request(self):
        for field, value in (("private", False), ("is_template", True)):
            api = build_api()
            api.responses[""][field] = value
            with self.assertRaises(merged_build.ApprovalError):
                merged_build.handle(api, 42)

    def test_non_pr_push_is_ignored_not_packaged(self):
        api = build_api()
        api.responses[f"/commits/{SOURCE}/pulls?per_page=100&page=1"] = []
        self.assertEqual(merged_build.handle(api, 42), {})

    def test_failed_ci_and_invalid_source_return_explicit_blocked_state(self):
        for mode in ("ci", "source"):
            api = build_api()
            if mode == "ci":
                api.responses["/actions/runs/42"]["conclusion"] = "failure"
            else:
                api.files(SOURCE)[0]["sha"] = "f" * 40
            with self.subTest(mode=mode):
                result = merged_build.handle(api, 42)
                self.assertEqual(result["stage"], "blocked")
                self.assertEqual(result["issue"], 1)
                self.assertNotIn("approval", result)


class ReviewScopeTests(unittest.TestCase):
    def test_follow_up_without_new_plan_is_allowed_before_merge(self):
        api = FakeGitHub()
        api.files(BASE).append({"path": "plans/1.json", "mode": "100644",
                                "type": "blob", "sha": PLAN_BLOB})
        review_scope.check_scope(api, 2, HEAD)

    def test_follow_up_reference_cannot_change_during_scope_check(self):
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
        with self.assertRaisesRegex(merged_build.ApprovalError, "changed"):
            review_scope.check_scope(api, 2, HEAD)

    def test_plan_and_implementation_use_same_main_target_pr(self):
        api = FakeGitHub()
        review_scope.check_scope(api, 2, HEAD)
        head = copy.deepcopy(api.files(BASE))
        head.append({"path": "plans/1.json", "sha": PLAN_BLOB, "mode": "100644", "type": "blob"})
        api.candidate(head)
        review_scope.check_scope(api, 2, HEAD)

    def test_scope_rejects_shared_changes_wrong_head_and_task_base(self):
        for mode in ("shared", "head", "base"):
            api = FakeGitHub()
            if mode == "shared":
                api.files(HEAD).append({"path": "run.py", "sha": "f" * 40, "mode": "100644", "type": "blob"})
            elif mode == "base":
                api.responses["/pulls/2"]["base"]["ref"] = "task/issue-1"
            with self.subTest(mode=mode), self.assertRaises(merged_build.ApprovalError):
                review_scope.check_scope(api, 2, BASE if mode == "head" else HEAD)


if __name__ == "__main__":
    unittest.main()
