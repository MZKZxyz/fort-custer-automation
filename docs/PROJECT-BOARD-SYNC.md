# Automated Fort Custer Project board

This workflow mirrors issue and PR lifecycle into the **existing user-owned GitHub
Projects v2 board (#1)**. It has no Codex, runtime, publishing, database, billing,
or deployment capability. It touches only Project membership, the single-select
`Status` value, and the archived flag for superseded/abandoned work.

## Rules

| GitHub source of truth | Target Status |
| --- | --- |
| Open issue with no status label | Backlog (or built-in Todo) |
| Open issue labeled `status:decision-needed` | Decision needed (or Todo) |
| Open issue labeled `status:ready` | Ready (or Todo) |
| Open issue labeled `status:in-progress` | In progress |
| Open issue labeled `status:in-review` | In review (or In progress) |
| Open issue labeled `status:blocked` | Blocked (or Todo) |
| Open draft PR, without explicit override | In progress |
| Open non-draft PR, without explicit override | In review (or In progress) |
| Closed completed issue / merged PR | Done |
| Closed `not planned` issue / unmerged closed PR | Archive item |

A status label **does not authorize agent execution**. In particular,
`automation:ready` is unrelated to Project Status and does not imply that an
agent should start.

A single explicit `status:*` label overrides an open item's default.
Conflicting labels fail the run before any mutation; correct the labels on
the original issue or PR. State from a closed issue/PR wins over labels.

With the default GitHub Project status options (Todo / In Progress / Done),
the workflow works with **no extra custom columns**. Adding the optional
Backlog, Decision needed, Ready, In review, and Blocked options later makes
those distinctions visible as separate columns.

New *open* client/server issues titled `[FC-...]` or `[Program]...`,
or carrying `project:track`, are automatically added to the board. New
*open* PRs titled `[FC-...]` or `[VIS-...]`, or carrying `project:track`,
are also added. Old unrelated PRs are not imported wholesale. Existing
project cards are reconciled even if they lack a tracking label. Other
repositories' cards, draft notes, and archived cards are never changed.

## One-time credential provisioning

The repository's built-in `GITHUB_TOKEN` cannot mutate a **user-owned**
Project. A trusted maintainer must set the Actions repository secret
`FORT_CUSTER_PROJECTS_TOKEN` in the **automation repository**, using a
classic PAT scoped to **`project`** (both tracked repositories are public).
Do not paste a token into an issue, PR, file, comment, or job log. If access
to private repositories is added, review any additional required scopes
rather than granting broad access by default. Prefer a dedicated GitHub App
credential with Projects write permissions when one becomes practical.

The workflow reads `PROJECT_OWNER` from the GitHub repository owner and uses
project number `1`; it discovers the field ID and option IDs dynamically,
so no personal username, token, or GraphQL node ID is stored in code.

1. Review and merge the single status-sync PR (no auto-merge).
2. Provision `FORT_CUSTER_PROJECTS_TOKEN` in repository Actions secrets.
3. From Actions → **Fort Custer Project board synchronization** → Run
   workflow, keep `dry_run=true` and check counts.
4. Run it with `dry_run=false` once to reconcile the current cards.
   Thereafter the scheduled run every 15 minutes reconciles both
   repositories automatically. GitHub scheduled runs may be delayed.
5. Agent or integrator changes a GitHub issue status by maintaining
   **one** `status:*` label; issue closure/PR draft/merge are inferred.
   No Project-field interaction is necessary for routine work.

The scheduled job will **fail without a token** rather than pretending to
have synchronized the board. It logs only operation counts and generic
errors; it never dumps project item bodies or secrets. A manual dry run also
requires the same read-capable project token.

## Safety, testing, and rollback

- Tests run locally and on PR without secrets:
  `python -m unittest discover -s tests -p 'test_project_status_sync.py' -v`.
- Pull requests do not execute a token-privileged synchronization job.
  Only default-branch manual and scheduled runs can write Project data.
- All pages of current board items and both repos' open issues and PRs are
  read before the first mutation. Missing fields, invalid data, conflicting
  labels, absent required options, inaccessible repos, API errors or
  truncated pagination stop the job.
- Writes are idempotent. Repeated syncs do not rewrite unchanged statuses.
  If an API operation fails midway, the next scheduled sync retries safely.
- The script does **not** create or edit issue labels, dispatch agents,
  close issues, merge PRs, update source code or deploy anything.
- To stop the automation, disable the scheduled workflow or remove its
  secret. Existing Project fields are left untouched; source issues and PRs
  remain authoritative. A rollback of the PR removes this workflow.
- No live authenticated Project mutation or real Project-field compatibility
  is claimed until the secret is installed and the manual dry run passes.

**Status ownership:** issues/PRs + explicit `status:*` labels are authoritative;
the Project is a derived presentation. Avoid manually updating the board's
Status field because the next successful sync may replace that edit.
