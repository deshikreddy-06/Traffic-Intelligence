# Hyderabad traffic data inventory

## Imported traffic observations

There are currently no eligible public Hyderabad road-level observations in the project database. No speed, vehicle-count, or density values have been inserted. The import API is ready for a dataset that has verifiable Hyderabad coverage, timestamped observations, coordinates inside the bundled GHMC polygon, measured values, and a reusable license.

## Public dataset reviewed and downloaded

**CHETNA-Road, Hyderabad CO₂ grid, 2021**

- Dataset record: [Figshare DOI 10.6084/m9.figshare.28330067.v2](https://doi.org/10.6084/m9.figshare.28330067.v2)
- License: CC BY 4.0.
- Artifact: [`datasets/chetnaroad_co2/52545989.nc`](datasets/chetnaroad_co2/52545989.nc), with inspection notes in [`datasets/chetnaroad_co2/README.md`](datasets/chetnaroad_co2/README.md).
- Coverage and period: Hyderabad grid, daily from 2021-01-01 through 2021-12-31; 500 m nominal grid.
- Data fields: CO₂ emissions (tonnes per grid cell), time, latitude and longitude.
- Missing traffic observation fields: measured speed, vehicle count, traffic density, road name and point-level traffic observation ID.
- Treatment: registered as `emissions_grid`; never loaded into `traffic_observations`. The source paper reports Hyderabad uncertainty class C.

## Hyderabad dataset requiring permission

**JICA, Traffic Survey for Assistance for the Introduction of ITS on road network in Hyderabad metropolitan area, Volume 1 (2011)**

- Official report: [JICA PDF](https://openjicareport.jica.go.jp/pdf/12150363_04.pdf).
- It contains site-level classified vehicle-count summaries and describes 15-minute surveys during weekday periods in late October/early November 2011. It does not provide measured vehicle speeds in this volume.
- JICA's [site policy](https://www.jica.go.jp/english/policy/) says reuse or reproduction for purposes beyond personal use is prohibited, with limited quotation for legally recognized purposes. This project therefore records it as a restricted candidate and does not extract or import report tables without permission.
- It is not established that every survey site falls inside the current GHMC polygon; any future authorized import must validate each coordinate.

## Other candidates excluded

- The Aalto/OpenICPSR mobility dataset estimates city-level speed indices from trips measured by a web mapping service. It is not raw road-level Hyderabad observation data and is not a suitable observation import.
- Open GitHub traffic CSVs without traceable Hyderabad collection provenance are not treated as real city observations.
- TomTom's public Hyderabad index is an aggregated city-level report, not a downloadable raw observation dataset suitable for this database.

## Required CSV/JSON/GeoJSON observation fields

Provide timestamp, area name, latitude, longitude, and at least one measured field among average speed, vehicle count, or traffic density. Road name and a source observation ID are recommended. Upload metadata must include source name, collection period, license, Hyderabad city coverage, and status (`actual` or `historical`). Records outside the GHMC boundary, duplicate IDs, invalid records, and simulated/predicted statuses are not inserted.

All imported observations are source-reported by the uploader. Source metadata is retained so provenance can be reviewed; the application does not independently certify a dataset's authenticity.
