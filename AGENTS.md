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
- Implement changes on a task branch, commit, push, and open a PR with base `dev`.
- Do this by default without separate prompts for commit/push/open PR.
- Never merge PRs or move anything to `main` unless explicitly requested.

8. Branch naming conventions
- Use `fix/...` for bug fixes.
- Use `feat/...` for features.
- Use `supabase/...` for Supabase/DB work.
- For Codex task branches use:
- `fix/codex/...`
- `feat/codex/...`
- `supabase/codex/...`

9. PR title and description required
- Every PR must include a clear, specific title.
- Every PR must include a structured description of what changed and why.
- Include validation notes (what checks were run and the result).

10. Documentation updates required after PR changes
- After every PR, update the relevant documentation sections/files to match the merged code behavior.
- Documentation updates are part of done criteria for each PR.

11. Docs-first rule for fixes/features
- For every fix or feature request, consult the relevant docs file(s) before making changes.
- Use worker-specific docs when touching worker logic:
- `docs/WORKER_IMPORT_COMPANIES.md`
- `docs/WORKER_EXTRACT_SITE_CONTENT.md`
- `docs/WORKER_JOB_EXTRACTION.md`
- Use `docs/DATABASE_SYSTEM_DOCUMENTATION.md` when changing schema, status flow, triggers, or DB access patterns.
