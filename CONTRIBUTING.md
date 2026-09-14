# Contributing

Practical Git and collaboration guidelines for the COMS6200 LLM-Based Network Troubleshooting Agent.

## Before starting work

Always start from the latest integration branch:

```bash
git switch develop
git pull origin develop
```

Do not start a new feature from stale local `develop`, and do not do normal development on `master`.

## Create a feature branch

```bash
git switch -c feature/<short-description>
```

Examples:

- `feature/topology`
- `feature/controller`
- `feature/telemetry`
- `feature/link-failure`
- `feature/llm-agent`
- `feature/baseline`

Keep one feature branch focused on one task.

## After implementation

```bash
git status
git add <specific files>
git commit -m "<meaningful message>"
git push -u origin feature/<branch>
```

Prefer adding specific files over `git add .` when you have unrelated local files.

## Pull requests and review

- Feature branches should normally be reviewed and merged into `develop`.
- Use a pull request or an explicit team review before integration.
- `master` is for stable / submission-ready work only.
- Do not push experimental work directly to `master`.

## Commit quality

- Avoid huge unrelated commits.
- Do not mix formatting-only changes with functional work unless the formatting is the task.
- Preserve other team members' code. Do not rewrite unrelated files.
- Pull the latest `develop` before starting a new feature, and again before opening a pull request if `develop` has moved.

## Secrets

- Do not commit secrets.
- Do not commit `.env`.
- Use `.env.example` as the committed template.
- OpenAI credentials belong in a local `.env` or environment variable as `OPENAI_API_KEY`.

## Shared-branch safety

- Do not force push shared branches (`master`, `develop`) unless the team has explicitly coordinated that action.
- Do not rebase shared history unless the team has agreed.
- Do not delete shared branches unless the team has agreed.

Git commit, push, merge, rebase, and history rewriting are human-controlled operations.
