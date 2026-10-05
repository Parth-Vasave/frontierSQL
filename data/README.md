# Dataset

## Source

**Our World in Data — CO₂ and Greenhouse Gas Emissions**
Repository: <https://github.com/owid/co2-data> · Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

OWID compiles this dataset from primary sources, listed per column in `owid-co2-codebook.csv`:

- Global Carbon Budget (2025): CO₂ emissions, by fuel, land-use change, consumption-based
- Jones et al. (2024): methane, nitrous oxide, total greenhouse gases, temperature change
- Energy Institute *Statistical Review of World Energy* and U.S. EIA: primary energy
- Maddison Project Database: GDP
- OWID population series (UN WPP, HYDE, Gapminder)

| | |
|---|---|
| Pinned commit | `382ee6c662b0ece26e111f263b44c029afad7787` |
| `owid-co2-data.csv` SHA-256 | `7f78e2b218ce4bb8c538bbec04fdc9a7982e8d40bff972e650df603899edd5f6` |
| `owid-co2-codebook.csv` SHA-256 | `33b4f5e00efd58c7b83863f736beba1af4df946b43642b0400c3ec38648e0e8e` |
| Retrieved | 2026-09-26 |
| Coverage | 1750–2024, 254 entities (242 after cleaning), 50,411 rows × 79 columns |

Attribution: *Our World in Data, "CO₂ and Greenhouse Gas Emissions", https://github.com/owid/co2-data.*

## Getting the data

```bash
python -m scripts.ingest_data     # downloads the pinned commit into data/raw/ and checks both SHA-256 hashes
python -m scripts.clean_data      # writes data/processed/*.csv and cleaning_report.json
ADMIN_DATABASE_URL=postgresql://... python -m scripts.seed_database
```

With Docker, `docker compose run --rm seed` runs all three steps. `data/raw/` and
`data/processed/` are git-ignored; the data is always rebuilt from the pinned source.
`data/raw/owid-co2.manifest.json` records the commit, download time and hashes of each run.

## Cleaning

1. All 46 source columns used by the schema must be present, or the run stops.
2. Entity names are trimmed; ISO codes must be three letters.
3. The 12 entities suffixed **"(GCP)"** (1,834 rows) are excluded. They are the Global
   Carbon Project's alternative region definitions, duplicating OWID's own regions
   ("Asia" vs "Asia (GCP)"), and would make region questions ambiguous.
4. Each entity is classified (`countries.entity_type`):
   - **country** (219): has an ISO code, plus Kosovo (no ISO code in OWID)
   - **region** (15): World, continents, EU-27/28, "Europe (excl. EU-27)", OECD, least developed countries
   - **income_group** (4): World Bank high / upper-middle / lower-middle / low income
   - **other** (4): International aviation, International shipping, Kuwaiti Oil Fires, Ryukyu Islands

   An entity with no ISO code that is not on these lists stops the run, so new OWID
   aggregates are never mislabeled as countries.
5. A duplicate (entity, year) stops the run (none exist).
6. Negative values in columns that cannot be negative are set to NULL and counted (none in
   the pinned version). Land-use change, trade, growth and total GHG can legitimately be negative and are kept.
7. Each table stores only the (entity, year) rows where at least one of its metrics is present.

Result (pinned version): `country_indicators` 41,243 rows, `co2_emissions` 45,950,
`ghg_emissions` 41,458.

**Not loaded:** 33 of the 79 source columns, all derivable from or variants of the ones kept:
per-fuel cumulative totals (6), per-fuel / land-use / cumulative global shares (16),
cement, flaring, land-use and other per-capita values (4), land-use-inclusive growth,
intensity and cumulative variants (6), and consumption CO₂ per GDP (1).
`cleaning_report.json` lists them exactly.

## Assumptions and caveats

- "Emissions" means annual CO₂ from fossil fuels and industry (`co2`, million tonnes) unless the question says per capita, land use, or greenhouse gases.
- Rankings of "countries" exclude aggregates (`entity_type = 'country'`); World and regions are not countries.
- **GDP ends in 2022**; all other series run to 2024. Early years (before about 1950) are sparse, and missing values are NULL, never zero.
- Methane, nitrous oxide and total GHG are in CO₂-equivalents over a 100-year timescale.
- Values are stored exactly as published; nothing is imputed or recalculated.

## Database schema

See [`database/schema.sql`](../database/schema.sql); every column has a comment with its unit.

| Table | Key | Contents |
|---|---|---|
| `countries` | `id` | name, ISO code, entity_type |
| `country_indicators` | `(country_id, year)` | population, GDP, primary energy, energy per capita and per GDP |
| `co2_emissions` | `(country_id, year)` | total and per-capita CO₂, by fuel, land use, consumption-based, trade, cumulative, global shares |
| `ghg_emissions` | `(country_id, year)` | methane, nitrous oxide, total GHG, per capita, temperature-change contribution |

## Benchmark data: BIRD Mini-Dev

Used only by the evaluation ([EVALUATION_PLAN.md](../EVALUATION_PLAN.md)), never by the app.

**BIRD Mini-Dev, PostgreSQL version** — <https://github.com/bird-bench/mini_dev> · Licence:
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). 500 questions over 11 databases
(75 tables, 3.9 million rows). Attribution: *Li et al., "Can LLM Already Serve as A Database
Interface? A BIg Bench for Large-Scale Database Grounded Text-to-SQLs" (BIRD), NeurIPS 2023.*

| | |
|---|---|
| Database dump | `BIRD_dev.sql` and `dev_tables.json` from the Mini-Dev package (`minidev_0703.zip`, SHA-256 `aeb211c0e39010bbdae3838bb5e8bd27dc446ed77495b1709f85ccc9bf67f2be`) |
| Questions | Hugging Face `birdsql/bird_mini_dev` revision `f65faf4`, `mini_dev_pg` (SHA-256 `7fa740ef9225389cff6c34432120e8325d0ca3008d73db1ae38731234bc10da7`); newer than the package's copy, with one ground-truth fix |

```bash
python -m scripts.bird download                            # ~800 MB download, keeps ~1 GB in data/raw/bird/
ADMIN_DATABASE_URL=postgresql://... python -m scripts.bird load   # needs psql; about 30 s
python -m evaluation.bird build-expected                   # ground truth into data/processed/bird/
```

With Docker: `docker compose run --rm seed python -m scripts.bird download`, then the same with
`load` (the seed image has psql). `load` creates the database `bird` on the same server as
`ADMIN_DATABASE_URL`, moves each BIRD database's tables into a schema of its own (`formula_1`,
`financial`, ...), and grants the existing `sql_agent` role CONNECT, USAGE and SELECT only. The
dump's `OWNER TO` statements name a role from the authors' machine and are skipped. Nothing else
is changed: no cleaning, no comments, data as published.
