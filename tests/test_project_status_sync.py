"""Offline contract checks for Project board sync; no API or secret access."""
import unittest

from src.project_status_sync import (
    SyncError, compute_plan, desired, get_project, get_repo_items,
    resolve_options, should_enroll,
)

REPO = "owner/fort-custer-client"
FIELD = {"id": "STATUS", "options": [
    {"id": "T", "name": "Todo"},
    {"id": "I", "name": "In Progress"},
    {"id": "D", "name": "Done"},
]}
EXTENDED = {"id": "STATUS", "options": FIELD["options"] + [
    {"id": "B", "name": "Blocked"},
    {"id": "V", "name": "In review"},
]}


def make_issue(number=1, state="OPEN", reason=None, names=(), title="[FC-TEST] Task"):
    return {
        "__typename": "Issue", "id": "issue" + str(number),
        "number": number, "title": title, "state": state,
        "stateReason": reason, "repository": {"nameWithOwner": REPO},
        "labels": {"nodes": [{"name": n} for n in names]},
    }


def make_pr(number=2, state="OPEN", draft=True, merged=False, names=()):
    return {
        "__typename": "PullRequest", "id": "pr" + str(number),
        "number": number, "title": "[VIS-02] Example", "state": state,
        "isDraft": draft, "mergedAt": "2026-10-24T00:00:00Z" if merged else None,
        "repository": {"nameWithOwner": REPO},
        "labels": {"nodes": [{"name": n} for n in names]},
    }


def row(content, value=None, archived=False):
    return {"id": "board-" + content["id"], "isArchived": archived,
            "content": content,
            "fieldValueByName": {"name": value} if value else None}


class DesiredStatusTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(desired(make_issue()), "backlog")
        self.assertEqual(desired(make_pr()), "in_progress")
        self.assertEqual(desired(make_pr(draft=False)), "in_review")

    def test_explicit_labels_take_precedence(self):
        self.assertEqual(desired(make_issue(names=["status:blocked"])), "blocked")
        self.assertEqual(desired(make_pr(names=["status:in-review"])), "in_review")
        self.assertEqual(desired(make_issue(names=["status:decision-needed"])),
                         "decision_needed")

    def test_conflicting_labels_fail_closed(self):
        with self.assertRaises(SyncError):
            desired(make_issue(names=["status:blocked", "status:ready"]))

    def test_closed_states_override_labels(self):
        self.assertEqual(desired(make_issue(state="CLOSED")), "done")
        self.assertEqual(desired(make_issue(state="CLOSED",
                                            reason="NOT_PLANNED")), "archive")
        self.assertEqual(desired(make_pr(state="MERGED", merged=True)), "done")
        self.assertEqual(desired(make_pr(state="CLOSED")), "archive")

    def test_no_false_enrollment(self):
        self.assertTrue(should_enroll(make_issue()))
        self.assertTrue(should_enroll(make_pr()))
        self.assertFalse(should_enroll(make_issue(title="Legacy fix")))
        self.assertFalse(should_enroll(make_pr(state="CLOSED")))
        self.assertTrue(should_enroll(make_issue(title="Legacy fix",
                                                 names=["project:track"])))

    def test_unrelated_labels_do_not_execute_agents(self):
        self.assertEqual(desired(make_issue(names=["automation:ready", "L0"])),
                         "backlog")


class PlanTests(unittest.TestCase):
    def test_builtin_status_options_work_without_custom_columns(self):
        options = resolve_options(FIELD)
        self.assertEqual(options["blocked"]["id"], "T")
        self.assertEqual(options["in_review"]["id"], "I")
        self.assertEqual(options["done"]["id"], "D")

    def test_use_extended_status_options_when_present(self):
        options = resolve_options(EXTENDED)
        self.assertEqual(options["blocked"]["id"], "B")
        self.assertEqual(options["in_review"]["id"], "V")

    def test_update_only_changed_fields(self):
        a = make_issue(names=["status:in-progress"])
        b = make_issue(number=3, state="CLOSED")
        actions = compute_plan([row(a, "Todo"), row(b, "Done")],
                               [a], FIELD, {REPO})
        self.assertEqual(actions, [("update", "board-issue1", "I")])

    def test_adds_recognized_new_issues_and_prs(self):
        a = make_issue()
        b = make_pr()
        changes = compute_plan([], [a, b], FIELD, {REPO})
        self.assertEqual(changes, [("add", "issue1", "T"),
                                   ("add", "pr2", "I")])

    def test_archives_superseded_issue_only(self):
        closed = make_issue(state="CLOSED", reason="NOT_PLANNED")
        self.assertEqual(compute_plan([row(closed, "Todo")], [], FIELD, {REPO}),
                         [("archive", "board-issue1", None)])

    def test_ignores_nonprogram_items_and_other_repositories(self):
        unrelated = make_issue(title="Not a sprint")
        foreign = make_issue(number=5)
        foreign["repository"]["nameWithOwner"] = "other/repository"
        self.assertEqual(compute_plan([], [unrelated, foreign], FIELD, {REPO}), [])

    def test_preserves_archived_cards(self):
        a = make_issue()
        self.assertEqual(compute_plan([row(a, "Todo", archived=True)],
                                      [], FIELD, {REPO}), [])

    def test_missing_required_column_aborts_preflight(self):
        a = make_issue(state="CLOSED")
        with self.assertRaisesRegex(SyncError, "Missing Status option"):
            compute_plan([row(a)], [], {"id": "S", "options": []}, {REPO})

    def test_invalid_duplicate_labels_aborts_preflight(self):
        a = make_issue(names=["status:in-progress", "status:blocked"])
        with self.assertRaisesRegex(SyncError, "Conflicting status"):
            compute_plan([row(a)], [], FIELD, {REPO})

    def test_duplicate_project_item_is_fatal(self):
        a = make_issue()
        with self.assertRaisesRegex(SyncError, "Duplicate"):
            compute_plan([row(a), row(a)], [], FIELD, {REPO})

    def test_idempotent_rerun(self):
        a = make_issue(names=["status:in-progress"])
        self.assertEqual(compute_plan([row(a, "In Progress")], [a],
                                      FIELD, {REPO}), [])


class PaginationTests(unittest.TestCase):
    def test_project_items_are_paged(self):
        calls = []

        def api(query, variables):
            calls.append(variables["after"])
            page = len(calls)
            return {"user": {"projectV2": {
                "id": "PROJECT", "fields": {"nodes": [FIELD]},
                "items": {"nodes": [{"id": str(page)}],
                          "pageInfo": {"hasNextPage": page == 1,
                                       "endCursor": "cursor" if page == 1 else None}}
            }}}

        pid, field, items = get_project(api, "owner", 1)
        self.assertEqual(pid, "PROJECT")
        self.assertEqual(field["id"], "STATUS")
        self.assertEqual([v["id"] for v in items], ["1", "2"])
        self.assertEqual(calls, [None, "cursor"])

    def test_repository_pagination_and_type(self):
        calls = []

        def api(query, variables):
            calls.append(variables["after"])
            page = len(calls)
            return {"repository": {"issues": {
                "nodes": [{"id": str(page)}],
                "pageInfo": {"hasNextPage": page == 1,
                             "endCursor": "next" if page == 1 else None}
            }}}

        items = get_repo_items(api, "owner", "fort-custer-client", True)
        self.assertEqual([i["__typename"] for i in items],
                         ["Issue", "Issue"])
        self.assertEqual(calls, [None, "next"])


if __name__ == "__main__":
    unittest.main()
