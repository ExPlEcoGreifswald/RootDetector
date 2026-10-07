FROM python:3.7.17-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Bullseye LTS repositories are archived; pin their final snapshot so this
# legacy Python 3.7 test image remains reproducible.
RUN sed -i \
        -e 's|http://deb.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/20260901T000000Z|' \
        -e 's|http://deb.debian.org/debian|https://snapshot.debian.org/archive/debian/20260901T000000Z|' \
        /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libglib2.0-0 \
        libgomp1 \
        libjpeg62-turbo \
        libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt requirements-core-test.txt constraints-legacy.txt /tmp/rootdetector/

RUN python -m pip install --upgrade \
        pip==23.1.2 \
        setuptools==63.1.0 \
        wheel==0.40.0 \
    && python -m pip install \
        --constraint /tmp/rootdetector/constraints-legacy.txt \
        --requirement /tmp/rootdetector/requirements.txt \
        --requirement /tmp/rootdetector/requirements-core-test.txt

CMD ["python", "main.py"]
