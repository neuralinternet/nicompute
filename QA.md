# Dev installation

There are additional requirements for local dev environment and CI. The one-line command to install everything is

```
pip install -e .[dev] -r requirements.txt -r requirements-dev.txt
```

# Requirements files

Are generated automatically by pip-compile in a pre-commit hook assuming hooks are installed (see below). Do not edit requirements.txt and requirements-dev.txt manually. Only edit pyproject.toml

It's also the configuration file of choice for all compatible tooling.


# Style guide and linting tools

We are starting to introduce pre-commit and adding checks to it and enabling GitHub Actions.

Locally, start by installing pre-commit package and running `scripts/install-dev.sh` - it will ensure checks are being run before each commit is made and in other situations.

Autolinting commits (made after running `pre-commit run -a` and fixing all files with new checks) are to be recorded in `.git-blame-ignore-revs` and that file can be used with git blame and git config snippet like this (or command-line `--ignore-revs-file`) to skip such commits when examining history.

```
[blame]
	ignoreRevsFile = .git-blame-ignore-revs
```
