#!/bin/bash
pip install -e .[dev] -r requirements.txt -r requirements-dev.txt
pre-commit install --install-hooks
pre-commit install -t commit-msg
pre-commit install -t post-checkout
pre-commit install -t pre-commit
pre-commit install -t pre-push
