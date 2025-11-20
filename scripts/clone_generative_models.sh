#!/usr/bin/env bash
set -e
if [ ! -d /content/generative-models ]; then
  git clone https://github.com/Stability-AI/generative-models.git /content/generative-models
fi
pip install -q -e /content/generative-models || true

