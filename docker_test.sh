#!/usr/bin/env bash
# docker_test.sh — Build and run headless tests in Docker (Ubuntu/Debian)
#
# Prerequisites: Docker Desktop installed and running.
#
# Usage:
#   chmod +x docker_test.sh
#   ./docker_test.sh
#
# This produces terminal output that serves as evidence for JORS
# requirement #4 (testing on a UNIX-based system).

set -e

echo "========================================"
echo " metaScreener — Linux headless test run"
echo "========================================"
echo ""

# Build the Docker image
echo "[1/2] Building Docker image..."
docker build -t metascreener-test . 2>&1 | tail -5
echo ""

# Run the test suite
echo "[2/2] Running pytest inside container..."
echo ""
docker run --rm metascreener-test 2>&1 | tee test_output_linux.txt

echo ""
echo "========================================"
echo " Test output saved to test_output_linux.txt"
echo " Use this as evidence for the JORS editor."
echo "========================================"
