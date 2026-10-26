# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
ARG FDO_CONSUME_SOURCE=https://github.com/FAIR2Adapt/fdo-consume/archive/6a65ac6a31a03204e063fcb7a8945d3c34550998.tar.gz

FROM ${PYTHON_IMAGE} AS build
ARG FDO_CONSUME_SOURCE

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
COPY . .

RUN pip install -r requirements.lock.txt "fdo-consume @ ${FDO_CONSUME_SOURCE}" jsonschema==4.26.0
RUN python -m unittest discover -s tests > /tmp/unittest.log 2>&1; status=$?; tail -n 3 /tmp/unittest.log; exit $status
RUN python scripts/build_site.py --config config/portugal-dashboard.yaml --require-data-origin real --out /tmp/site-check && rm -rf /tmp/site-check

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin dashboard \
 && mkdir -p /app /data/site /app/snapshots \
 && chown -R dashboard:dashboard /data /app/snapshots

WORKDIR /app

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build --chown=dashboard:dashboard /src/listing ./listing
COPY --from=build --chown=dashboard:dashboard /src/scripts ./scripts
COPY --from=build --chown=dashboard:dashboard /src/web ./web
COPY --from=build --chown=dashboard:dashboard /src/config ./config
COPY --from=build --chown=dashboard:dashboard /src/snapshots ./snapshots
COPY --from=build --chown=dashboard:dashboard /src/server.py /src/LICENSE ./

USER dashboard

EXPOSE 8020

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=2 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8020/api/v1/health', timeout=3).status == 200 else 1)"

CMD ["python", "server.py", "--dist", "/data/site", "--host", "0.0.0.0", "--port", "8020"]
