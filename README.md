# FDO Knowledge Dashboard

![Python](https://img.shields.io/badge/Python-3.12-3776AB) ![RO-Crate](https://img.shields.io/badge/RO--Crate-Metadata-2A9D8F) ![License](https://img.shields.io/badge/License-MIT-green)

A configurable dashboard for exploring scientific resources represented as **FAIR Digital Objects (FDOs)**.

Developed within FAIR2Adapt WP4, this prototype supports resource browsing, metadata search, filtering, and exploration of scientific claims and provenance. It uses [fdo-consume](https://github.com/FAIR2Adapt/fdo-consume) to process FDO metadata from ROHub and generate a structured catalog for web-based exploration.

The same application can be configured for different case studies and deployed as a static website or through an optional server.

## Features

- Resource browsing, search, filtering, and details
- Scientific claims and provenance where available
- Configurable FDO collections and dashboard presentation
- Optional integration interfaces for QA and graph discovery
- Static builds with recorded metadata snapshots
- Standalone and embedded presentation modes

## Online demo

The Portugal Knowledge Dashboard is an initial prototype based on the CS4 design mockups. It presents metadata from three
CS4 publication FDOs in ROHub, using recorded metadata snapshots, with configurable branding and styling for different case
studies over a shared layout. Planned GitHub Pages address: [https://fair2adapt.github.io/fdo-knowledge-dashboard/](https://fair2adapt.github.io/fdo-knowledge-dashboard/)


## Getting Started

**Requirements:** Python 3.12 and `fdo-consume` v1.1.0+.

```bash
git clone https://github.com/FAIR2Adapt/fdo-knowledge-dashboard.git
git clone https://github.com/FAIR2Adapt/fdo-consume.git
cd fdo-knowledge-dashboard

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt ../fdo-consume

python server.py
```

Open `http://localhost:8010`.

### Static Build

```bash
python scripts/build_site.py --config config/portugal-dashboard.yaml --out dist
python server.py --dist dist --port 8020
```

The generated site can be hosted on GitHub Pages or another static hosting service.

## Configurations

| Configuration | Dashboard | FDO source |
|---|---|---|
| `config/portugal-dashboard.yaml` (default) | Portugal Adaptation Dashboard (CS4) | Three publication FDOs selected by PID |
| `config/nordic-dashboard.yaml` | Nordic Climate Science Dashboard (reuse demonstration) | Public FDOs selected from a ROHub community |

Both configurations use the same application, FDO consumption pipeline, consumer contracts, and profile mappings. They differ in resource selection, content, and presentation settings.

Configurations define FDO sources, metadata mappings, dashboard content, and optional knowledge services. 

## Tests

```bash
CI=1 python -m unittest discover -s tests
```

## Integration and Deployment

The dashboard supports static deployment, optional Python/Node HTTP servers, and embedding public views in external websites.

`.github/workflows/pages.yml` builds the Portugal configuration from its recorded snapshot and deploys it to GitHub Pages on
every push to `main`; `refresh.yml` records the members again from ROHub by hand. Container: `docker compose build dashboard`,
`docker compose --profile ops run --rm build`, then `docker compose up -d dashboard` (http://127.0.0.1:8020).

QA and graph-discovery interfaces currently use provisional contracts and local mocks; partner services are not yet connected. Remote integrations may require a separate backend for authentication.

Note: The dashboard presents metadata provided by FDO sources; it does not independently validate scientific claims.