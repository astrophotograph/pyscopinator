#!/bin/bash
# Install git hooks that mirror CI checks.
# Run once from the repo root: ./install-hooks.sh

set -e

HOOK_DIR="$(git rev-parse --git-dir)/hooks"
HOOK_FILE="$HOOK_DIR/pre-push"

cat > "$HOOK_FILE" << 'EOF'
#!/bin/bash
# Pre-push hook: runs the same checks as CI before allowing a push.

set -e

echo "==> pre-push: running CI checks..."

echo ""
echo "[1/3] ruff check src/"
uv run ruff check src/

echo ""
echo "[2/3] ruff format --check src/"
uv run ruff format --check src/

echo ""
echo "[3/3] pytest tests/unit/ (not hardware)"
uv run pytest tests/unit/ -q --tb=short -m "not hardware"

echo ""
echo "==> All checks passed."
EOF

chmod +x "$HOOK_FILE"
echo "Installed pre-push hook at $HOOK_FILE"
