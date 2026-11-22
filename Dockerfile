# Radar's production image, run by Azure App Service.
# Secrets are never baked in: .dockerignore leaves out .env, and every setting comes from environment
# variables when the container starts.
FROM python:3.12-slim-bookworm
# Links the published image to the repository on GitHub.
LABEL org.opencontainers.image.source=https://github.com/AnniecTW/1-radar

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=radar.settings.production \
    PORT=8000

# GeoDjango needs GDAL, GEOS and PROJ (gdal-bin pulls in all three); binutils lets Python find them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin binutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Collect static files into the image. Settings need a secret key and a database URL to load, so give
# placeholders: collectstatic never connects to the database.
RUN DJANGO_SECRET_KEY=collectstatic-only DATABASE_URL=postgres://build:build@localhost:5432/build \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 radar && chown -R radar /app
USER radar

EXPOSE 8000
# Workers, port and log format are in gunicorn.conf.py. Migrations are not run here: the database is shared,
# so they stay a manual step.
CMD ["gunicorn", "radar.wsgi:application"]
