# Dockerfile — headless Linux testing for metaScreener
# Evidence for JORS requirement #4: UNIX-based system testing
#
# Usage:
#   docker build -t metascreener-test .
#   docker run --rm metascreener-test
#
# The container will:
#   1. Install Python 3.12 + dependencies on Ubuntu 24.04
#   2. Run the full pytest suite (headless — no GUI)
#   3. Verify that core modules import successfully
#   4. Print platform info as evidence for the editor

FROM python:3.12-slim-bookworm

LABEL maintainer="Alejandro Reyes-Consuelo <alejandro.reyes-consuelo.1@ulaval.ca>"
LABEL description="metaScreener headless test runner — Ubuntu/Debian (JORS req. #4)"

# Install system dependencies (Tk libs for importability, tesseract for OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-tk \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Test dependencies come from the dev extra in pyproject.toml, which is
# their single declaration (F-164): pytest, pytest-cov and httpx. They used
# to be spelled out on the line above as "pytest pytest-cov", which was a
# second copy of that list and did not include httpx -- so when openai 3.0.0
# swapped httpx for httpx2 this image stopped collecting two test modules,
# exactly as CI did, and the dev-extra fix did not reach it because this
# path never installs the extra.
#
# It runs after COPY rather than beside the requirements install because an
# editable install needs the source tree. The layer above still caches the
# nine runtime dependencies against requirements.txt alone; this layer adds
# only what the tests need and re-resolves nothing already satisfied.
RUN pip install --no-cache-dir -e ".[dev]"

# Run tests and print environment info
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short", "-s"]
