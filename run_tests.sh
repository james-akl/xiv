#!/bin/sh
# Test xiv across Python 2.7, 3.3-3.14 via Docker

set -e

INTEGRATION=0
VERBOSE=0
VERSIONS="2.7 3.3 3.4 3.5 3.6 3.7 3.8 3.9 3.10 3.11 3.12 3.13 3.14"

while [ $# -gt 0 ]; do
    case "$1" in
        --integration) INTEGRATION=1; shift ;;
        -v|--verbose) VERBOSE=1; shift ;;
        -h|--help)
            echo "Usage: $0 [--integration] [--verbose]"
            echo "Test xiv across Python 2.7, 3.3-3.14"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

PYTEST_FLAGS=""
[ "$INTEGRATION" = "1" ] && PYTEST_FLAGS="--integration" && echo "Mode: Integration (real arXiv API)"
[ "$INTEGRATION" = "0" ] && echo "Mode: Unit (mocked)"
[ "$VERBOSE" = "1" ] && PYTEST_FLAGS="$PYTEST_FLAGS -v"

echo "Testing Python: $VERSIONS"
echo ""

passed=0
total=0
failed=""

for v in $VERSIONS; do
    printf "%-6s " "$v"
    docker pull python:$v-slim >/dev/null 2>&1 || { echo "SKIP"; continue; }
    total=$((total + 1))

    if [ "$VERBOSE" = "1" ]; then
        docker run --rm -v "$(pwd)":/app -w /app python:$v-slim \
            sh -c "pip install pytest >/dev/null 2>&1 && pytest $PYTEST_FLAGS"
        result=$?
    else
        docker run --rm -v "$(pwd)":/app -w /app python:$v-slim \
            sh -c "pip install pytest >/dev/null 2>&1 && pytest $PYTEST_FLAGS" >/dev/null 2>&1
        result=$?
    fi

    if [ $result -eq 0 ]; then
        echo "PASS"
        passed=$((passed + 1))
    else
        echo "FAIL"
        failed="$failed $v"
    fi
done

echo ""
echo "$passed/$total passed"
[ $passed -ne $total ] && echo "Failed: $failed" && exit 1
exit 0
