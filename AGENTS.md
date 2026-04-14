# Agent Rules For This Repo

## Active rules
1. Tone + brevity
- Direct, minimal, no fluff, no assumptions.

2. No cleanup surprises
- Never delete branches, PRs, or files unless explicitly requested.

3. Verification required
- After edits, run targeted checks and report exactly what passed/failed.

4. Strict status/behavior preservation
- No behavior changes beyond the requested fix.
- If a side effect is needed, call it out before applying changes.

5. Plan first, edit second
- For any non-trivial task, provide a 3-7 line plan and wait for "go".

6. Patch preview before apply
- Show exact intended file diffs (or summary by file/line) before writing changes.

7. Git/PR workflow default
- For every coding task, branch from `dev`.
- Implement changes on a task branch.
- Verify changes locally.
- **WAIT** for explicit user confirmation before merging into `dev` or opening a PR.
- Never merge PRs or move anything to `main` unless explicitly requested.

8. Branch naming conventions
- Use `fix/...` for bug fixes.
- Use `feat/...` for features.
- Use `supabase/...` for Supabase/DB work.

9. PR title and description required
- Every PR must include a clear, specific title.
- Every PR must include a structured description of what changed and why.
- Include validation notes (what checks were run and the result).

10. Documentation updates required after PR changes
- After every PR, update the relevant documentation sections/files to match the merged code behavior.
- Documentation updates are part of done criteria for each PR.
- `docs/CAUGHT_ERRORS_REFERENCE.md` must be updated in every PR when error handling changes or new catches are added.

11. Docs-first rule for fixes/features
- For every fix or feature request, consult the relevant docs file(s) before making changes.
- Use worker-specific docs when touching worker logic:
- `docs/HELPER_IMPORT_COMPANIES.md`
- `docs/WORKER_EXTRACT_SITE_CONTENT.md`
- `docs/HELPER_JOB_EXTRACTION.md`
- Use `docs/DATABASE_SYSTEM_DOCUMENTATION.md` when changing schema, status flow, triggers, or DB access patterns.

12. No unrequested scope in plans
- Do not add extra plan items beyond the user's request unless explicitly approved first.

13. Stop before PR flow
- Stop before commit/push/PR and leave local edits for review.
- Share exactly what changed with file references, then wait for confirmation.

14. File responsibility boundaries
- Anything dealing with database access/status updates belongs in `database/database.py`.
- Anything dealing with AI connection/setup belongs in `database/AI_connection/AI.py`.

15. Pull latest before feature/fix work
- Before starting any feature or fix task, run `git pull` to sync latest changes.
