# CHETNA-Road Hyderabad CO₂ grid (non-traffic observation data)

- Dataset: High-resolution gridded CO₂ and pollutant emission data from road traffic in Indian cities (CHETNA-Road), Hyderabad CO₂ product.
- Source record: https://doi.org/10.6084/m9.figshare.28330067.v2
- Direct Hyderabad file URL: https://ndownloader.figshare.com/files/52545989
- License: Creative Commons Attribution 4.0 International (CC BY 4.0); attribute the dataset authors and DOI when reusing.
- Citation: Mittakola et al. (2025), *High-resolution gridded CO₂ and pollutant emission data from road traffic in Indian cities*, Scientific Data, DOI 10.6084/m9.figshare.28330067.v2.
- City: Hyderabad, Telangana, India. The downloaded NetCDF metadata identifies `city=Hyderabad` and `state=Telangana`.
- Collection period: 1 January–31 December 2021, daily.
- Spatial coverage: latitude 17.2920825–17.5570825, longitude 78.2717722–78.6167722; the grid file identifies Hyderabad/Telangana.
- Spatial resolution: approximately 500 m (0.005 degrees); NetCDF grid shape is 365 time steps × 54 latitude points × 70 longitude points; grid cell values are CO₂ emissions in tonnes.
- Inspected data quality: 766,135 finite grid cell/day values and 613,565 missing grid cell/day values (1,379,700 possible values total).
- Available data: daily gridded CO₂ emissions, plus time/latitude/longitude grid dimensions and file metadata.
- Not available: raw vehicle speed, vehicle count, traffic density, named roads/areas, or individual traffic observations.
- Quality/context: derived emissions were computed with COPERT using traffic activity and speed-dependent emission factors; they are not observed speeds or counts. Hyderabad is in the authors' highest uncertainty class (C).

This file is retained for provenance and possible emissions analysis only. It is deliberately not imported into `traffic_observations` or used in traffic analytics/predictions. Hyderabad is classified in the authors' highest uncertainty class (C).

- Downloaded file size: 11,050,923 bytes.
- SHA-256: `cc9e46a273117d5ad6a1eb76912609141e85eac0a5bcade2ec934f17b48158dc`.
