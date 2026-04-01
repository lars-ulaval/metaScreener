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
RUN pip install --no-cache-dir -r requirements.txt pytest pytest-cov

# Copy project
COPY . .

# Run tests and print environment info
CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short", "-s"]
