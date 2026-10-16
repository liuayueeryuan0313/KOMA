#!/usr/bin/env bash
# ==============================================================================
# 课间 · KOMA 一键安装与部署脚本
# 项目主页: https://github.com/liuayueeryuan0313/KOMA
# Docker Hub: https://hub.docker.com/r/aweo/koma
# ==============================================================================

set -euo pipefail

# 终端彩色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 确保以 bash 执行
if [ -z "${BASH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    else
        echo "错误: 本脚本需要 bash 环境执行，请使用 bash 运行。"
        exit 1
    fi
fi

# 支持管道输入交互 (如 curl ... | bash)
if [ ! -t 0 ] && [ -e /dev/tty ]; then
    exec < /dev/tty
fi

echo -e "${CYAN}${BOLD}"
echo "=========================================================="
echo "          欢迎使用 课间 · KOMA 一键部署脚本              "
echo "   将教学课表与实验课表整理成自己的日历订阅 (Docker)      "
echo "=========================================================="
echo -e "${NC}"

# 1. 检查必要命令 (curl / wget)
HTTP_GET=""
if command -v curl >/dev/null 2>&1; then
    HTTP_GET="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
    HTTP_GET="wget -qO-"
fi

# 2. 检查 Docker 环境
log_info "正在检查 Docker 环境..."

if ! command -v docker >/dev/null 2>&1; then
    log_warn "未检测到 Docker。"
    echo -e "你可以通过 Docker 官方一键脚本进行安装："
    echo -e "  ${CYAN}curl -fsSL https://get.docker.com | sh${NC}"
    echo -e "安装完成后，请启动 Docker 并将当前用户加入 docker 用户组，然后重新运行本脚本。"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    log_error "Docker 服务未在运行，或当前用户无权限访问 Docker 守护进程。"
    echo -e "提示："
    echo -e "  - 请尝试启动 Docker 服务: ${CYAN}sudo systemctl start docker${NC}"
    echo -e "  - 若是权限问题，请使用 sudo 运行本脚本，或执行: ${CYAN}sudo usermod -aG docker \$USER${NC} 后重新登录。"
    exit 1
fi
log_success "Docker 运行正常。"

# 3. 检查 Docker Compose
DOCKER_COMPOSE=""
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
else
    log_error "未检测到 Docker Compose (v2 插件或独立 docker-compose)。"
    echo -e "请安装 Docker Compose 插件后重新运行本脚本。"
    exit 1
fi
log_success "检测到 Compose: $($DOCKER_COMPOSE version | head -n 1)"

# 4. 确定安装目录
# 若当前目录下已有完整的 KOMA 源码或 compose.yaml，则直接在当前目录部署；否则使用 ./koma 目录
INSTALL_DIR="koma"
if [ -f "compose.yaml" ] || [ -f "docker-compose.yml" ]; then
    INSTALL_DIR="."
fi

if [ "$INSTALL_DIR" != "." ]; then
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

TARGET_PATH="$(pwd)"
log_info "部署工作目录: ${TARGET_PATH}"

# 5. 生成或确认 compose.yaml
if [ ! -f "compose.yaml" ] && [ ! -f "docker-compose.yml" ]; then
    log_info "正在生成 compose.yaml 部署配置..."
    cat << 'EOF' > compose.yaml
name: koma
services:
  komama:
    image: aweo/koma:latest
    init: true
    ports:
      - "${BIND_ADDRESS:-0.0.0.0}:${PORT:-8080}:8080"
    environment:
      PUBLIC_URL: ${PUBLIC_URL:-http://localhost:8080}
      COOKIE_SECURE: ${COOKIE_SECURE:-false}
      ALLOW_REGISTRATION: ${ALLOW_REGISTRATION:-true}
      ADMIN_USERNAME: ${ADMIN_USERNAME:-}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD:-}
    volumes:
      - komama-data:/data
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp:size=96m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
volumes:
  komama-data:
EOF
    log_success "已创建 compose.yaml。"
else
    log_info "检测到已有 compose.yaml，跳过创建。"
fi

# 6. 检测局域网 IP
LOCAL_IP="localhost"
if command -v ip >/dev/null 2>&1; then
    DETECTED_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' | head -n 1 || true)
    if [ -n "$DETECTED_IP" ]; then
        LOCAL_IP="$DETECTED_IP"
    fi
elif command -v hostname >/dev/null 2>&1; then
    DETECTED_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    if [ -n "$DETECTED_IP" ]; then
        LOCAL_IP="$DETECTED_IP"
    fi
fi

# 7. 生成或确认 .env
DEFAULT_PORT="8080"
if [ ! -f ".env" ]; then
    log_info "正在生成环境变量配置 .env..."

    PORT="$DEFAULT_PORT"
    PUBLIC_URL="http://${LOCAL_IP}:${PORT}"

    # 如果处于交互式终端，给予用户自定义机会
    if [ -t 0 ]; then
        echo -e "\n${BOLD}配置向导（直接回车即可使用推荐默认值）：${NC}"
        read -r -p "请输入访问端口 [默认: ${DEFAULT_PORT}]: " USER_PORT
        PORT="${USER_PORT:-$DEFAULT_PORT}"

        RECOMMENDED_URL="http://${LOCAL_IP}:${PORT}"
        read -r -p "请输入对外访问地址 PUBLIC_URL [默认: ${RECOMMENDED_URL}]: " USER_URL
        PUBLIC_URL="${USER_URL:-$RECOMMENDED_URL}"
    fi

    cat << EOF > .env
BIND_ADDRESS=0.0.0.0
PORT=${PORT}
PUBLIC_URL=${PUBLIC_URL}
COOKIE_SECURE=false
ALLOW_REGISTRATION=true
ADMIN_USERNAME=
ADMIN_PASSWORD=
EOF
    log_success "已创建 .env 配置文件。"
else
    log_info "检测到已有 .env 配置文件，保留现有配置。"
fi

# 8. 拉取最新镜像并启动服务
log_info "正在从 Docker Hub (aweo/koma:latest) 拉取镜像..."
$DOCKER_COMPOSE pull

log_info "正在启动 KOMA 容器服务..."
if $DOCKER_COMPOSE up -d --wait 2>/dev/null; then
    log_success "容器已成功启动。"
else
    log_warn "--wait 参数不被支持或启动耗时较长，切换至常规后台启动..."
    $DOCKER_COMPOSE up -d
    sleep 3
fi

# 9. 获取首次管理员设置码
log_info "正在检索首次管理员设置码 (Setup Token)..."
SETUP_TOKEN=""
for i in {1..20}; do
    SETUP_TOKEN=$($DOCKER_COMPOSE exec -T komama cat /data/setup-token 2>/dev/null || true)
    if [ -n "$SETUP_TOKEN" ]; then
        break
    fi
    sleep 1
done

# 读取 .env 中实际生效的端口与 URL
ACTUAL_PORT=$(grep "^PORT=" .env 2>/dev/null | cut -d '=' -f 2 || echo "8080")
ACTUAL_URL=$(grep "^PUBLIC_URL=" .env 2>/dev/null | cut -d '=' -f 2 || echo "http://${LOCAL_IP}:${ACTUAL_PORT}")

echo -e "\n${GREEN}${BOLD}==========================================================${NC}"
echo -e "${GREEN}${BOLD}             🎉 课间 · KOMA 部署成功！                    ${NC}"
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo -e "  ${BOLD}工作目录${NC}  : ${TARGET_PATH}"
echo -e "  ${BOLD}访问地址${NC}  : ${CYAN}${ACTUAL_URL}${NC}"
if [ "$LOCAL_IP" != "localhost" ] && [ "$ACTUAL_URL" != "http://localhost:${ACTUAL_PORT}" ]; then
    echo -e "  ${BOLD}本机访问${NC}  : ${CYAN}http://localhost:${ACTUAL_PORT}${NC}"
fi

if [ -n "$SETUP_TOKEN" ]; then
    echo -e "\n  ${BOLD}首次管理员设置码 (Setup Token):${NC}"
    echo -e "  ${YELLOW}${BOLD}${SETUP_TOKEN}${NC}"
    echo -e "\n  ${BOLD}下一步操作：${NC}"
    echo -e "  1. 打开浏览器访问：${CYAN}${ACTUAL_URL}${NC}"
    echo -e "  2. 点击页面右上角的 ${BOLD}“管理员设置”${NC}"
    echo -e "  3. 粘贴上述设置码，设置用户名与站内密码即可完成初始管理员创建。"
else
    echo -e "\n  ${YELLOW}提示: 未能直接读取到 setup-token，可能是您已设置过管理员账户，或容器仍在初始化中。${NC}"
    echo -e "  如需手动查看设置码，请执行: ${CYAN}docker compose exec komama cat /data/setup-token${NC}"
fi

echo -e "\n${BOLD}常用管理命令（在 ${TARGET_PATH} 目录下执行）：${NC}"
echo -e "  - 查看服务日志: ${CYAN}$DOCKER_COMPOSE logs -f komama${NC}"
echo -e "  - 重启容器服务: ${CYAN}$DOCKER_COMPOSE restart${NC}"
echo -e "  - 停止容器服务: ${CYAN}$DOCKER_COMPOSE stop${NC}"
echo -e "  - 升级最新版本: ${CYAN}$DOCKER_COMPOSE pull && $DOCKER_COMPOSE up -d${NC}"
echo -e "${GREEN}==========================================================${NC}\n"
