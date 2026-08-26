# syntax=docker/dockerfile:1

##############################################################################
# Stage 1 — build a self-contained virtualenv.
##############################################################################
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# INSTALL_DEV=true adds the test/lint toolchain; the production image leaves it false.
ARG INSTALL_DEV=false

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt \
 && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

##############################################################################
# Stage 2 — runtime image.
##############################################################################
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=soleir.settings

# psycopg[binary] ships its own libpq, so no system PostgreSQL client is needed.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin soleire

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=soleire:soleire . .

# Build the hashed static manifest at image-build time so the running container
# never needs write access to the source tree. No database is touched here.
RUN DJANGO_DEBUG=false \
    DJANGO_SECRET_KEY=build-time-only-not-a-real-secret \
    python manage.py collectstatic --noinput --clear \
 && chown -R soleire:soleire /app/staticfiles

USER soleire
EXPOSE 8000

# Uses the stdlib rather than adding curl to the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "soleir.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
