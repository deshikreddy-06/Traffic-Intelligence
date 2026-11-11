# Phase 3B: Hyderabad traffic data access review

Research checked on 2026-11-03. No externally released dataset was imported during this phase.

## CHETNA-Road floating-car observations

The CHETNA-Road paper describes Nexqt street-level floating-car data from 2021. The underlying FCD had timestamps, speed, count, direction and 10–50 m road segments, including Hyderabad. The observation series were hourly and based on GPS-equipped cars and trucks. The public Figshare release is the processed daily 500 m emission grids for 15 cities, not a release of those raw/hourly FCD measurements. The paper also describes imputation and scaling in the emission analysis; those values must not be substituted for source observations.

- Paper: https://doi.org/10.1038/s41597-025-06287-9
- Public emissions release: https://doi.org/10.6084/m9.figshare.28330067
- Corresponding author access request: Chuanlong Zhou, chuanlong.zhou@lsce.ipsl.fr
- Data provider contact: https://nexqt.com/en/contact (hello@nexqt.com)

The raw feed is not currently a public downloadable project dataset. Request access and explicit reuse/storage rights from the authors/provider. This project has not contacted them.

## Other Hyderabad sources

- JICA Hyderabad traffic volume survey (2011): https://openjicareport.jica.go.jp/pdf/12150363_04.pdf. The report contains historical classified volume survey summaries, not live readings or speed series. Project source notes record reuse restrictions; obtain permission before extracting and storing report tables.
- CHETNA-Road: public, but emissions-only at daily gridded resolution; unsuitable for traffic speed/count imports.
- No freely downloadable, provenance-verifiable Hyderabad road-level dataset with measured speed, vehicle count, timestamps and coordinates was found in this review.

## Free traffic API review

TomTom's official pricing page lists the legacy Traffic Flow API Segment Data with 20,000 free monthly requests, no credit card for signup, and says the endpoint returns live road-segment traffic flow. The legacy Traffic API market coverage table includes India. This establishes a free request allowance and India country coverage, not that every GHMC road is covered, nor that a developer may archive or train on the response indefinitely.

TomTom's newer Intermediate Traffic evaluation is request/approval-based and explicitly limited to Amsterdam, Barcelona, Munich, Detroit, Montreal and Melbourne; Hyderabad is not among those evaluation cities. TomTom's current public API documentation and terms reviewed here did not establish a clear retention/training license for persistent archival of segment responses. Therefore this project does not store TomTom data or describe it as an available project source. Use only for display after account/terms review, unless TomTom confirms storage and analysis rights in writing.

- Pricing: https://docs.tomtom.com/pricing
- Traffic Flow API India coverage: https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/product-information/market-coverage
- Traffic Flow API description: https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/traffic-flow-service
- Intermediate evaluation city coverage: https://docs.tomtom.com/intermediate-traffic-service/documentation/tomtom-orbis-maps/evaluation-api/overview
- API terms overview: https://www.tomtom.com/en-gb/legal/third-party-product-terms/

## Project GPS contributions

The opt-in collector stores only individual device movement samples, derived from consecutive fixes and labeled `consented_foreground_browser_gps` / `observed_individual_gps_speed`. They are not traffic counts or road-wide speeds. Records are separate from imported `traffic_observations`, and never affect the traffic-observation dashboard totals. Collection requires an explicit checkbox, is foreground-only, and stops on user action, page hiding, navigation, or GPS errors. The app offers deletion by session ID. A participant's samples cannot establish traffic volume or representativeness; that requires multiple independent contributors or an authorized aggregate sensor/FCD dataset and a documented aggregation procedure.

Current realistic project collection is **zero until a participant opts in and contributes**. Once users contribute, the raw number depends on their active, quality-filtered sessions. Each accepted sample needs a pair of fixes 3–120 seconds apart, accurate to 25 m or better, within GHMC, with resolvable movement and a derived speed no greater than 120 km/h. Counts cannot be inferred from this collector.

## Data distinctions

| Signal | Meaning | Stored/used as |
| --- | --- | --- |
| Consented GPS speed | Approximate speed between two fixes from one device | Separate individual GPS speed table/API |
| Observed vehicle count | Count directly reported by an authorized detector/dataset | Traffic observations only, with provenance |
| Historical traffic measurement | Source-reported past measurement | Traffic observations with historical status |
| OSRM route duration | Routing-engine travel-time estimate | Route response only; not observed/live traffic |
| Predicted traffic | Model output based on suitable training data | Unavailable until sufficient labeled data and model validation |

