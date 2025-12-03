#!/bin/bash

set -e -o pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"

SERVER_DIR="$WORKSPACE_DIR/vespa"
ENV_PATH="$WORKSPACE_DIR/worker-env"
DEBUG_LOG="$WORKSPACE_DIR/debug.log"
VESPA_LOG="$WORKSPACE_DIR/vespa.log"

REPORT_ADDR="${REPORT_ADDR:-https://run.vast.ai}"
export VESPA_USE_SSL="${VESPA_USE_SSL:-true}"
export VESPA_WORKER_PORT="${VESPA_WORKER_PORT:-3000}"
mkdir -p "$WORKSPACE_DIR"
cd "$WORKSPACE_DIR"

# make all output go to $DEBUG_LOG and stdout without having to add `... | tee -a $DEBUG_LOG` to every command
exec &> >(tee -a "$DEBUG_LOG")

function echo_var(){
    echo "$1: ${!1}"
}

# MODEL_LOG is no longer required (no log tailing), but we keep for compatibility
MODEL_LOG="${MODEL_LOG:-/tmp/model.log}"

# HF_TOKEN might be needed by model server
[ -z "$HF_TOKEN" ] && echo "Warning: HF_TOKEN not set (may be required by model server)"

echo "start_server.sh"
date

echo_var REPORT_ADDR
echo_var WORKSPACE_DIR
echo_var SERVER_DIR
echo_var ENV_PATH
echo_var DEBUG_LOG
echo_var VESPA_LOG
echo "VESPA_WORKER_PORT: ${VESPA_WORKER_PORT:-3000}"
echo "VESPA_USE_SSL: ${VESPA_USE_SSL:-true}"
echo "VESPA_BACKEND_URL: ${VESPA_BACKEND_URL:-not set}"
echo "VESPA_BENCHMARK: ${VESPA_BENCHMARK:-none}"

# if instance is rebooted, we want to clear out the log file so pyworker doesn't read lines
# from the run prior to reboot. past logs are saved in $MODEL_LOG.old for debugging only
if [ -e "$MODEL_LOG" ]; then
    echo "Rotating model log at $MODEL_LOG to $MODEL_LOG.old"
    cat "$MODEL_LOG" >> "$MODEL_LOG.old" 
    : > "$MODEL_LOG"
fi

# Populate /etc/environment with quoted values
if ! grep -q "VAST" /etc/environment; then
    env -0 | grep -zEv "^(HOME=|SHLVL=)|CONDA" | while IFS= read -r -d '' line; do
            name=${line%%=*}
            value=${line#*=}
            printf '%s="%s"\n' "$name" "$value"
        done > /etc/environment
fi

if [ ! -d "$ENV_PATH" ]
then
    echo "setting up venv"
    if ! which uv; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source ~/.local/bin/env
    fi

    # Fork testing
    [[ ! -d $SERVER_DIR ]] && git clone "${VESPA_REPO:-https://github.com/robballantyne/vespa}" "$SERVER_DIR"
    if [[ -n ${VESPA_REF:-} ]]; then
        (cd "$SERVER_DIR" && git checkout "$VESPA_REF")
    fi

    uv venv --python-preference only-managed "$ENV_PATH" -p 3.10
    source "$ENV_PATH/bin/activate"

    uv pip install -r "${SERVER_DIR}/requirements.txt"

    touch ~/.no_auto_tmux
else
    [[ -f ~/.local/bin/env ]] && source ~/.local/bin/env
    source "$WORKSPACE_DIR/worker-env/bin/activate"
    echo "environment activated"
    echo "venv: $VIRTUAL_ENV"
fi

# Validate VESPA_BACKEND_URL is set
if [ -z "$VESPA_BACKEND_URL" ]; then
    echo "ERROR: VESPA_BACKEND_URL must be set!"
    echo "Example: VESPA_BACKEND_URL=http://localhost:8000"
    exit 1
fi

# Validate server.py exists
if [ ! -f "$SERVER_DIR/server.py" ]; then
    echo "ERROR: $SERVER_DIR/server.py not found!"
    exit 1
fi

if [ "$VESPA_USE_SSL" = true ]; then

    cat << EOF > /etc/openssl-san.cnf
    [req]
    default_bits       = 2048
    distinguished_name = req_distinguished_name
    req_extensions     = v3_req

    [req_distinguished_name]
    countryName         = US
    stateOrProvinceName = CA
    organizationName    = Vast.ai Inc.
    commonName          = vast.ai

    [v3_req]
    basicConstraints = CA:FALSE
    keyUsage         = nonRepudiation, digitalSignature, keyEncipherment
    subjectAltName   = @alt_names

    [alt_names]
    IP.1   = 0.0.0.0
EOF

    openssl req -newkey rsa:2048 -subj "/C=US/ST=CA/CN=pyworker.vast.ai/" \
        -nodes \
        -sha256 \
        -keyout /etc/instance.key \
        -out /etc/instance.csr \
        -config /etc/openssl-san.cnf

    curl --header 'Content-Type: application/octet-stream' \
        --data-binary @//etc/instance.csr \
        -X \
        POST "https://console.vast.ai/api/v0/sign_cert/?instance_id=$CONTAINER_ID" > /etc/instance.crt;
fi




export REPORT_ADDR

cd "$SERVER_DIR"

echo "launching Vespa server"

set +e
python3 server.py |& tee -a "$VESPA_LOG"
PY_STATUS=${PIPESTATUS[0]}
set -e

if [ "${PY_STATUS}" -ne 0 ]; then
  echo "Vespa exited with status ${PY_STATUS}; notifying autoscaler..."
  ERROR_MSG="Vespa exited: code ${PY_STATUS}"
  MTOKEN="${MASTER_TOKEN:-}"
  VERSION="${VESPA_VERSION:-0}"

  IFS=',' read -r -a REPORT_ADDRS <<< "${REPORT_ADDR}"
  for addr in "${REPORT_ADDRS[@]}"; do
    curl -sS -X POST -H 'Content-Type: application/json' \
      -d "$(cat <<JSON
{
  "id": ${CONTAINER_ID:-0},
  "mtoken": "${MTOKEN}",
  "version": "${VERSION}",
  "loadtime": 0,
  "new_load": 0,
  "cur_load": 0,
  "rej_load": 0,
  "max_perf": 0,
  "cur_perf": 0,
  "error_msg": "${ERROR_MSG}",
  "num_requests_working": 0,
  "num_requests_recieved": 0,
  "additional_disk_usage": 0,
  "working_request_idxs": [],
  "cur_capacity": 0,
  "max_capacity": 0,
  "url": "${URL}"
}
JSON
)" "${addr%/}/worker_status/" || true
  done
fi

echo "launching Vespa server done"