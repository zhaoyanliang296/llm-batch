# Contributing

Thanks for taking the time to contribute! 

This is a small project, so the process is lightweight 
but a few guidelines keep things smooth.

## Getting started

1. Fork the repo and clone your fork.
2. Install dependencies:

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
```

3. Create a branch for your work:

```bash
git checkout -b fix/my-change
```

## Running tests

```bash
python -m pytest -q
```

Tests should pass before you open a pull request. 
If a test is broken on `main`, open an issue first.

## Code style

- functions stay small; extract early
- comments explain *why*, not *what*
- no new dependencies without a good reason
- match the surrounding style, do not reformat unrelated code

## Linting

```bash
python -m compileall -q .
```

## Pull request process

1. Open an issue for anything bigger than a typo 
   so we can agree on the approach first.
2. Keep the diff focused: one thing per PR.
3. Write commit messages in imperative mood 
   (e.g. "fix crash on empty input" not "fixed").
4. Reference the issue in the PR description (e.g. "closes #12").
5. Make sure CI is green before requesting review.

## Reporting issues

- Include the command you ran and the output you saw.
- Mention your OS and version.
- A minimal reproducer is the fastest path to a fix.

## Code of conduct

By participating you agree to uphold the [Code of Conduct](CODE_OF_CONDUCT.md).
