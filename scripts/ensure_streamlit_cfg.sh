#!/bin/bash
# Idempotently write ~/.streamlit/credentials.toml + config.toml so Streamlit
# never blocks on the first-run "Welcome ... Email:" prompt. Called from
# scripts/start_stack.ps1 pre-flight; safe to re-run by hand any time.
set -e

D="$HOME/.streamlit"
mkdir -p "$D"

if [ ! -f "$D/credentials.toml" ]; then
    cat > "$D/credentials.toml" <<'EOF'
[general]
email = ""
EOF
    echo "  wrote $D/credentials.toml"
fi

if [ ! -f "$D/config.toml" ]; then
    cat > "$D/config.toml" <<'EOF'
[server]
headless = true
port = 8501
address = "0.0.0.0"

[browser]
gatherUsageStats = false
EOF
    echo "  wrote $D/config.toml"
fi

echo OK
