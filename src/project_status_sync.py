"""GitHub Project v2 status synchronizer. Standard library; project-only writes."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com/graphql"
LABELS = {f"status:{name.replace('_', '-')}": name for name in
          ("backlog", "decision_needed", "ready", "in_progress", "in_review", "blocked")}
ALIASES = {
    "backlog": ("Backlog", "Todo", "To do"),
    "decision_needed": ("Decision needed", "Todo", "To do", "Backlog"),
    "ready": ("Ready", "Todo", "To do", "Backlog"),
    "in_progress": ("In progress",),
    "in_review": ("In review", "In progress"),
    "blocked": ("Blocked", "Todo", "To do", "Backlog"),
    "done": ("Done",),
}
PROJECT = """
query($owner:String!, $number:Int!, $after:String) {
 user(login:$owner) { projectV2(number:$number) {
  id fields(first:100) { nodes { ... on ProjectV2SingleSelectField {
   id name options { id name } } } }
  items(first:100,after:$after) {
   pageInfo { hasNextPage endCursor }
   nodes { id isArchived
    fieldValueByName(name:"Status") {
     ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { __typename
     ... on Issue { id number title state stateReason
      repository { nameWithOwner } labels(first:100) { nodes { name } } }
     ... on PullRequest { id number title state isDraft mergedAt
      repository { nameWithOwner } labels(first:100) { nodes { name } } }
    }
   }
  }
 } }
}
"""
REPO = """
query($owner:String!, $repo:String!, $after:String, $issues:Boolean!) {
 repository(owner:$owner,name:$repo) {
  issues(first:100,after:$after,states:OPEN,
   orderBy:{field:CREATED_AT,direction:DESC}) @include(if:$issues) {
    pageInfo { hasNextPage endCursor }
    nodes { id number title state stateReason
     repository { nameWithOwner } labels(first:100) { nodes { name } } }
  }
  pullRequests(first:100,after:$after,states:OPEN,
   orderBy:{field:CREATED_AT,direction:DESC}) @skip(if:$issues) {
    pageInfo { hasNextPage endCursor }
    nodes { id number title state isDraft mergedAt
     repository { nameWithOwner } labels(first:100) { nodes { name } } }
  }
 }
}
"""
ADD = """mutation($p:ID!,$c:ID!){
 addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}
}"""
UPDATE = """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
 updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,
 value:{singleSelectOptionId:$o}}){projectV2Item{id}}
}"""
ARCHIVE = """mutation($p:ID!,$i:ID!){
 archiveProjectV2Item(input:{projectId:$p,itemId:$i}){item{id}}
}"""


class SyncError(Exception):
    pass


def graphql(token, query, variables):
    data = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=data, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "fort-custer-project-status-sync",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        raise SyncError("GitHub GraphQL HTTP error " + str(e.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SyncError("GitHub GraphQL request failed") from e
    if result.get("errors") or not isinstance(result.get("data"), dict):
        # Never expose raw server responses or user-authored issue content in logs.
        raise SyncError("GitHub GraphQL rejected operation")
    return result["data"]


def get_project(call, owner, number):
    out, cursor, field = [], None, None
    for _ in range(20):
        project = (call(PROJECT, {"owner": owner, "number": number,
                                  "after": cursor}).get("user") or {}).get("projectV2")
        if project is None:
            raise SyncError("Project unavailable; verify number and token scope")
        if field is None:
            candidates = [f for f in project["fields"]["nodes"] if f and
                          f.get("name", "").casefold() == "status" and "options" in f]
            if len(candidates) != 1:
                raise SyncError("Expected one single-select Status field")
            field = candidates[0]
        page = project["items"]
        out.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return project["id"], field, out
        cursor = page["pageInfo"].get("endCursor")
        if not cursor:
            raise SyncError("Project page missing cursor")
    raise SyncError("Project exceeds safe pagination limit")


def get_repo_items(call, owner, repo, issues):
    out, cursor = [], None
    key = "issues" if issues else "pullRequests"
    for _ in range(20):
        repository = call(REPO, {"owner": owner, "repo": repo,
                                 "after": cursor, "issues": issues}).get("repository")
        if repository is None:
            raise SyncError("Repository unavailable")
        page = repository[key]
        for item in page["nodes"]:
            item["__typename"] = "Issue" if issues else "PullRequest"
            out.append(item)
        if not page["pageInfo"]["hasNextPage"]:
            return out
        cursor = page["pageInfo"].get("endCursor")
        if not cursor:
            raise SyncError("Repository page missing cursor")
    raise SyncError("Repository exceeds safe pagination limit")


def label_names(item):
    return {x["name"].lower() for x in (item.get("labels") or {}).get("nodes", [])}


def desired(item):
    if item["__typename"] == "Issue":
        if item["state"] != "OPEN":
            return "archive" if item.get("stateReason") == "NOT_PLANNED" else "done"
    elif item["__typename"] == "PullRequest":
        if item["state"] != "OPEN":
            return "done" if item.get("mergedAt") else "archive"
    else:
        return None
    overrides = sorted(label_names(item).intersection(LABELS))
    if len(overrides) > 1:
        raise SyncError("Conflicting status labels")
    if overrides:
        return LABELS[overrides[0]]
    if item["__typename"] == "PullRequest":
        return "in_progress" if item.get("isDraft") else "in_review"
    return "backlog"


def should_enroll(item):
    if item["state"] != "OPEN":
        return False
    name = item.get("title") or ""
    return ("project:track" in label_names(item) or name.startswith("[FC-")
            or name.startswith("[Program]") or
            (item["__typename"] == "PullRequest" and name.startswith("[VIS-")))


def resolve_options(field):
    found = {}
    for option in field["options"]:
        k = option["name"].strip().casefold()
        if k in found:
            raise SyncError("Duplicate Status option name")
        found[k] = option
    return {status: next((found[n.casefold()] for n in names
                           if n.casefold() in found), None)
            for status, names in ALIASES.items()}


def compute_plan(project_items, fresh_items, field, repositories):
    """Verify entire plan before applying any mutation. Return idempotent operations."""
    options = resolve_options(field)
    seen, actions = set(), []
    for row in project_items:
        content = row.get("content")
        if (row.get("isArchived") or not content or
                content.get("__typename") not in ("Issue", "PullRequest")):
            continue
        if content["repository"]["nameWithOwner"] not in repositories:
            continue
        if content["id"] in seen:
            raise SyncError("Duplicate content in Project")
        seen.add(content["id"])
        status = desired(content)
        if status == "archive":
            actions.append(("archive", row["id"], None))
        elif status:
            option = options.get(status)
            if not option:
                raise SyncError("Missing Status option: " + status)
            current = ((row.get("fieldValueByName") or {}).get("name") or "").casefold()
            if current != option["name"].casefold():
                actions.append(("update", row["id"], option["id"]))
    fresh_seen = set()
    for content in fresh_items:
        if content["repository"]["nameWithOwner"] not in repositories or not should_enroll(content):
            continue
        if content["id"] in fresh_seen:
            raise SyncError("Duplicate repository content")
        fresh_seen.add(content["id"])
        if content["id"] in seen:
            continue
        status = desired(content)
        option = options.get(status)
        if not option:
            raise SyncError("Missing Status option: " + str(status))
        actions.append(("add", content["id"], option["id"]))
    return actions


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    owner, token = os.getenv("PROJECT_OWNER", ""), os.getenv("PROJECTS_SYNC_TOKEN", "")
    number = int(os.getenv("PROJECT_NUMBER", "1"))
    if not owner or not token or number < 1:
        raise SyncError("Set valid PROJECT_OWNER, PROJECT_NUMBER and PROJECTS_SYNC_TOKEN")
    call = lambda query, variables: graphql(token, query, variables)
    project_id, field, project_rows = get_project(call, owner, number)
    repos = {owner + "/fort-custer-client", owner + "/fort-custer-server"}
    fresh = []
    for repo in ("fort-custer-client", "fort-custer-server"):
        for issues in (True, False):
            fresh.extend(get_repo_items(call, owner, repo, issues))
    actions = compute_plan(project_rows, fresh, field, repos)
    counts = {op: sum(a[0] == op for a in actions)
              for op in ("add", "update", "archive")}
    print("Project reconciliation:", counts,
          "(dry run)" if args.dry_run else "(apply)")
    if args.dry_run:
        return 0
    for op, item_id, option_id in actions:
        if op == "archive":
            call(ARCHIVE, {"p": project_id, "i": item_id})
        elif op == "update":
            call(UPDATE, {"p": project_id, "i": item_id,
                          "f": field["id"], "o": option_id})
        else:
            added = call(ADD, {"p": project_id, "c": item_id})
            new = (added.get("addProjectV2ItemById") or {}).get("item")
            if not new or not new.get("id"):
                raise SyncError("Project addition not confirmed")
            call(UPDATE, {"p": project_id, "i": new["id"],
                          "f": field["id"], "o": option_id})
    print("Project reconciliation completed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SyncError, ValueError, KeyError, TypeError) as error:
        print("Project reconciliation failed:", error, file=sys.stderr)
        sys.exit(1)
