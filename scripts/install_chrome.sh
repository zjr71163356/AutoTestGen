#!/usr/bin/env bash
set -euo pipefail

KEYRING=/usr/share/keyrings/google-chrome.gpg
REPO_FILE=/etc/apt/sources.list.d/google-chrome.list
REPO_LINE="deb [arch=amd64 signed-by=${KEYRING}] http://dl.google.com/linux/chrome/deb/ stable main"

echo ">>> Importing Google signing key"
wget -qO - https://dl.google.com/linux/linux_signing_key.pub \
  | sudo gpg --dearmor --yes -o "${KEYRING}"

echo ">>> Writing APT source"
printf '%s\n' "${REPO_LINE}" | sudo tee "${REPO_FILE}" > /dev/null

echo ">>> Updating package index"
sudo apt update

echo ">>> Installing google-chrome-stable"
sudo apt install -y google-chrome-stable

echo "Chrome installation complete."
