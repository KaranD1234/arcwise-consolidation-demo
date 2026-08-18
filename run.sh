#!/usr/bin/env bash
# Launch the Arcwise Consolidation Demo.
#
# Run from anywhere: paths inside the app are resolved relative to the repo
# root, never to the working directory, so this is safe to host later.
set -euo pipefail
cd "$(dirname "$0")"
exec streamlit run app/Home.py "$@"
