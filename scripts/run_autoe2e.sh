#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PETCLINIC_DIR="${REPO_ROOT}/benchmark/pet-clinic"
PETCLINIC_FRONTEND_DIR="${PETCLINIC_DIR}/spring-petclinic-angular"
PETCLINIC_TMP_DIR="${REPO_ROOT}/tmp/petclinic"
mkdir -p "${PETCLINIC_TMP_DIR}"

PETCLINIC_FRONTEND_PID=""
PETCLINIC_BACKEND_CLEANUP="none"

cleanup() {
  if [[ -n "${PETCLINIC_FRONTEND_PID}" ]] && kill -0 "${PETCLINIC_FRONTEND_PID}" 2>/dev/null; then
    echo ">>> 停止 PetClinic 前端 (PID ${PETCLINIC_FRONTEND_PID})"
    kill "${PETCLINIC_FRONTEND_PID}" 2>/dev/null || true
    wait "${PETCLINIC_FRONTEND_PID}" 2>/dev/null || true
  fi

  case "${PETCLINIC_BACKEND_CLEANUP}" in
    remove)
      echo ">>> 清理 PetClinic 后端容器"
      docker rm -f petclinic >/dev/null 2>&1 || true
      ;;
    stop)
      echo ">>> 停止 PetClinic 后端容器"
      docker stop petclinic >/dev/null 2>&1 || true
      ;;
  esac
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令：$1，请先安装。" >&2
    exit 1
  fi
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local retries="${3:-60}"
  local delay="${4:-2}"
  for ((i = 1; i <= retries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo ">>> ${label} 就绪（第 ${i} 次检测）"
      return 0
    fi
    sleep "${delay}"
  done
  echo "等待 ${label} 可用超时：${url}" >&2
  exit 1
}

start_petclinic_backend() {
  require_cmd docker
  echo ">>> 启动 PetClinic REST 后端（Docker）"
  local running
  running=$(docker ps -q --filter "name=^petclinic$" --filter "status=running")
  if [[ -n "${running}" ]]; then
    echo ">>> PetClinic 后端容器已在运行"
  else
    local existing
    existing=$(docker ps -aq --filter "name=^petclinic$")
    if [[ -n "${existing}" ]]; then
      docker start petclinic >/dev/null
      PETCLINIC_BACKEND_CLEANUP="stop"
    else
      docker run -d -p 9966:9966 --name=petclinic --entrypoint=/app/entrypoint.sh \
        webappdockers/petclinic-rest:latest >/dev/null
      PETCLINIC_BACKEND_CLEANUP="remove"
    fi
  fi
  wait_for_http "http://localhost:9966/petclinic/api/owners" "PetClinic 后端 API" 60 2
}

start_petclinic_frontend() {
  require_cmd npm
  require_cmd python3
  echo ">>> 构建 PetClinic Angular 前端"
  if [[ ! -d "${PETCLINIC_FRONTEND_DIR}/node_modules" ]]; then
    echo ">>> 安装前端依赖（npm install --legacy-peer-deps）"
    (cd "${PETCLINIC_FRONTEND_DIR}" && npm install --legacy-peer-deps)
  fi

  local build_dir="${PETCLINIC_TMP_DIR}/dist"
  rm -rf "${build_dir}"
  (cd "${PETCLINIC_FRONTEND_DIR}" && \
    npm run build -- \
      --configuration=production \
      --base-href=/petclinic/ \
      --deploy-url=/petclinic/ \
      --output-path="${build_dir}")

  local serve_root="${PETCLINIC_TMP_DIR}/serve"
  rm -rf "${serve_root}"
  mkdir -p "${serve_root}/petclinic"
  cp -R "${build_dir}/." "${serve_root}/petclinic/"

  local log_file="${PETCLINIC_TMP_DIR}/frontend.log"
  PETCLINIC_FRONTEND_PORT=4200 PETCLINIC_SERVE_ROOT="${serve_root}" \
    python3 - <<'PY' > "${log_file}" 2>&1 &
import http.server
import os
import pathlib
import socketserver

ROOT = pathlib.Path(os.environ["PETCLINIC_SERVE_ROOT"]).resolve()
PORT = int(os.environ.get("PETCLINIC_FRONTEND_PORT", "4200"))
FALLBACK = ROOT / "petclinic" / "index.html"


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path == "/":
            path = "/petclinic/"
        return str((ROOT / path.lstrip("/")).resolve())

    def do_GET(self):
        if self.path == "/":
            self.path = "/petclinic/"
        return super().do_GET()

    def send_head(self):
        path = pathlib.Path(self.translate_path(self.path))
        if path.is_dir():
            index = path / "index.html"
            if index.exists():
                path = index
        if not path.exists():
            path = FALLBACK
        ctype = self.guess_type(str(path))
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        self.send_response(200)
        self.send_header("Content-type", ctype)
        fs = os.fstat(f.fileno())
        self.send_header("Content-Length", str(fs.st_size))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f


with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), SpaHandler) as httpd:
    httpd.serve_forever()
PY
  PETCLINIC_FRONTEND_PID=$!
  echo ">>> 前端日志：${log_file}"
  wait_for_http "http://localhost:4200/petclinic/" "PetClinic 前端" 120 2
}

start_petclinic_stack() {
  require_cmd curl
  start_petclinic_backend
  start_petclinic_frontend
}

trap cleanup EXIT INT TERM

cd "${REPO_ROOT}"

ENV_FILE="${REPO_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
fi

missing_vars=()
for var in APP_NAME ANTHROPIC_API_KEY ATLAS_URI; do
  if [[ -z "${!var:-}" ]]; then
    missing_vars+=("${var}")
  fi
done

if [[ ${#missing_vars[@]} -gt 0 ]]; then
  echo "以下环境变量缺失，请在 .env 中配置：${missing_vars[*]}" >&2
  exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "提示：GH_TOKEN 未设置，webdriver_manager 下载驱动可能触发 GitHub rate limit。" >&2
fi

if [[ "${APP_NAME}" == "PETCLINIC" ]]; then
  start_petclinic_stack
fi

echo "使用 APP_NAME=${APP_NAME} 的配置运行 AutoE2E..."
exec env PYTHONUNBUFFERED=1 uv run python -u main.py "$@"
