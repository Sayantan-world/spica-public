# Loads host-local package paths from .packages.env.sh (gitignored).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "${ROOT}/.packages.env.sh" ]; then
  cp "${ROOT}/packages.env.sh.example" "${ROOT}/.packages.env.sh"
fi
# shellcheck disable=SC1091
source "${ROOT}/.packages.env.sh"
