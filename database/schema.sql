-- FrontierSQL — analytical schema for Our World in Data CO2 and greenhouse gas emissions.
--
-- Source: https://github.com/owid/co2-data (CC BY 4.0), see data/README.md.
-- One source row = one entity (country or aggregate region) and year. It is split into
-- thematic tables that share (country_id, year) so the SQL generator only sees the
-- columns relevant to a question.
--
-- Column comments are intentional: the schema retriever reads them as metadata (units!).
-- This script is idempotent and is run by the database owner, never by sql_agent.

\set ON_ERROR_STOP on
SET client_min_messages = warning;

CREATE TABLE IF NOT EXISTS countries (
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    iso_code     char(3) UNIQUE,
    entity_type  text NOT NULL,
    CONSTRAINT countries_entity_type_check
        CHECK (entity_type IN ('country', 'region', 'income_group', 'other'))
);

COMMENT ON TABLE countries IS 'Countries and aggregate entities (World, continents, EU, income groups). Filter entity_type = ''country'' when ranking or comparing countries.';
COMMENT ON COLUMN countries.name IS 'Entity name as published by Our World in Data, e.g. India, United States, World, Europe.';
COMMENT ON COLUMN countries.iso_code IS 'ISO 3166-1 alpha-3 code, e.g. IND, USA. NULL for aggregates and Kosovo.';
COMMENT ON COLUMN countries.entity_type IS 'country | region (World, continents, EU, OECD) | income_group (World Bank income groups) | other (international aviation/shipping, Kuwaiti oil fires, Ryukyu Islands).';

CREATE TABLE IF NOT EXISTS country_indicators (
    country_id                  integer NOT NULL REFERENCES countries (id),
    year                        smallint NOT NULL,
    population                  bigint CHECK (population >= 0),
    gdp                         numeric CHECK (gdp >= 0),
    primary_energy_consumption  numeric CHECK (primary_energy_consumption >= 0),
    energy_per_capita           numeric CHECK (energy_per_capita >= 0),
    energy_per_gdp              numeric CHECK (energy_per_gdp >= 0),
    PRIMARY KEY (country_id, year)
);

COMMENT ON TABLE country_indicators IS 'Yearly population, GDP and primary energy use per entity.';
COMMENT ON COLUMN country_indicators.year IS 'Calendar year.';
COMMENT ON COLUMN country_indicators.population IS 'Population (people).';
COMMENT ON COLUMN country_indicators.gdp IS 'Gross domestic product, international-$ at 2011 prices (Maddison Project). Available up to 2022 only.';
COMMENT ON COLUMN country_indicators.primary_energy_consumption IS 'Primary energy consumption, terawatt-hours (TWh).';
COMMENT ON COLUMN country_indicators.energy_per_capita IS 'Primary energy consumption per person, kilowatt-hours per person (kWh/person).';
COMMENT ON COLUMN country_indicators.energy_per_gdp IS 'Primary energy consumption per unit of GDP, kilowatt-hours per international-$ (kWh/$).';

CREATE TABLE IF NOT EXISTS co2_emissions (
    country_id                    integer NOT NULL REFERENCES countries (id),
    year                          smallint NOT NULL,
    co2                           numeric CHECK (co2 >= 0),
    co2_per_capita                numeric CHECK (co2_per_capita >= 0),
    co2_per_gdp                   numeric CHECK (co2_per_gdp >= 0),
    co2_per_unit_energy           numeric CHECK (co2_per_unit_energy >= 0),
    co2_growth_abs                numeric,
    co2_growth_prct               numeric,
    coal_co2                      numeric CHECK (coal_co2 >= 0),
    oil_co2                       numeric CHECK (oil_co2 >= 0),
    gas_co2                       numeric CHECK (gas_co2 >= 0),
    cement_co2                    numeric CHECK (cement_co2 >= 0),
    flaring_co2                   numeric CHECK (flaring_co2 >= 0),
    other_industry_co2            numeric CHECK (other_industry_co2 >= 0),
    coal_co2_per_capita           numeric CHECK (coal_co2_per_capita >= 0),
    oil_co2_per_capita            numeric CHECK (oil_co2_per_capita >= 0),
    gas_co2_per_capita            numeric CHECK (gas_co2_per_capita >= 0),
    land_use_change_co2           numeric,
    co2_including_luc             numeric,
    co2_including_luc_per_capita  numeric,
    consumption_co2               numeric CHECK (consumption_co2 >= 0),
    consumption_co2_per_capita    numeric CHECK (consumption_co2_per_capita >= 0),
    trade_co2                     numeric,
    trade_co2_share               numeric,
    cumulative_co2                numeric CHECK (cumulative_co2 >= 0),
    share_global_co2              numeric,
    share_global_cumulative_co2   numeric,
    PRIMARY KEY (country_id, year)
);

COMMENT ON TABLE co2_emissions IS 'Yearly carbon dioxide (CO2) emissions per entity, total and by source. Units: million tonnes (Mt) unless stated.';
COMMENT ON COLUMN co2_emissions.year IS 'Calendar year.';
COMMENT ON COLUMN co2_emissions.co2 IS 'Annual fossil and industry CO2 emissions, excluding land-use change, million tonnes (Mt). Default metric for "CO2 emissions".';
COMMENT ON COLUMN co2_emissions.co2_per_capita IS 'Annual CO2 emissions per person, tonnes per person (t/person).';
COMMENT ON COLUMN co2_emissions.co2_per_gdp IS 'Annual CO2 emissions per unit of GDP, kilograms per international-$ (kg/$).';
COMMENT ON COLUMN co2_emissions.co2_per_unit_energy IS 'Annual CO2 emissions per unit of primary energy, grams per kilowatt-hour (g/kWh).';
COMMENT ON COLUMN co2_emissions.co2_growth_abs IS 'Absolute change in annual CO2 emissions from the previous year, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.co2_growth_prct IS 'Percentage change in annual CO2 emissions from the previous year, percent (%).';
COMMENT ON COLUMN co2_emissions.coal_co2 IS 'Annual CO2 emissions from coal, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.oil_co2 IS 'Annual CO2 emissions from oil, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.gas_co2 IS 'Annual CO2 emissions from natural gas, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.cement_co2 IS 'Annual CO2 emissions from cement production, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.flaring_co2 IS 'Annual CO2 emissions from gas flaring, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.other_industry_co2 IS 'Annual CO2 emissions from other industry sources, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.coal_co2_per_capita IS 'Annual CO2 emissions from coal per person, tonnes per person (t/person).';
COMMENT ON COLUMN co2_emissions.oil_co2_per_capita IS 'Annual CO2 emissions from oil per person, tonnes per person (t/person).';
COMMENT ON COLUMN co2_emissions.gas_co2_per_capita IS 'Annual CO2 emissions from gas per person, tonnes per person (t/person).';
COMMENT ON COLUMN co2_emissions.land_use_change_co2 IS 'Annual CO2 emissions from land-use change (e.g. deforestation), million tonnes (Mt). Can be negative (net removal).';
COMMENT ON COLUMN co2_emissions.co2_including_luc IS 'Annual CO2 emissions including land-use change, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.co2_including_luc_per_capita IS 'Annual CO2 emissions including land-use change per person, tonnes per person (t/person).';
COMMENT ON COLUMN co2_emissions.consumption_co2 IS 'Annual consumption-based (trade-adjusted) CO2 emissions, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.consumption_co2_per_capita IS 'Annual consumption-based CO2 emissions per person, tonnes per person (t/person).';
COMMENT ON COLUMN co2_emissions.trade_co2 IS 'CO2 emissions embedded in trade (consumption minus production), million tonnes (Mt). Positive = net importer of CO2.';
COMMENT ON COLUMN co2_emissions.trade_co2_share IS 'CO2 embedded in trade as a percentage of production-based emissions, percent (%).';
COMMENT ON COLUMN co2_emissions.cumulative_co2 IS 'Cumulative CO2 emissions since the first recorded year, million tonnes (Mt).';
COMMENT ON COLUMN co2_emissions.share_global_co2 IS 'Share of global annual CO2 emissions, percent (%).';
COMMENT ON COLUMN co2_emissions.share_global_cumulative_co2 IS 'Share of global cumulative CO2 emissions, percent (%).';

CREATE TABLE IF NOT EXISTS ghg_emissions (
    country_id                             integer NOT NULL REFERENCES countries (id),
    year                                   smallint NOT NULL,
    methane                                numeric CHECK (methane >= 0),
    methane_per_capita                     numeric CHECK (methane_per_capita >= 0),
    nitrous_oxide                          numeric CHECK (nitrous_oxide >= 0),
    nitrous_oxide_per_capita               numeric CHECK (nitrous_oxide_per_capita >= 0),
    total_ghg                              numeric,
    total_ghg_excluding_lucf               numeric,
    ghg_per_capita                         numeric,
    ghg_excluding_lucf_per_capita          numeric,
    temperature_change_from_ghg            numeric,
    temperature_change_from_co2            numeric,
    temperature_change_from_ch4            numeric,
    temperature_change_from_n2o            numeric,
    share_of_temperature_change_from_ghg   numeric,
    PRIMARY KEY (country_id, year)
);

COMMENT ON TABLE ghg_emissions IS 'Yearly greenhouse gas emissions (methane, nitrous oxide, total GHG) and contribution to global warming per entity.';
COMMENT ON COLUMN ghg_emissions.year IS 'Calendar year.';
COMMENT ON COLUMN ghg_emissions.methane IS 'Annual methane (CH4) emissions, million tonnes of CO2-equivalents (MtCO2e).';
COMMENT ON COLUMN ghg_emissions.methane_per_capita IS 'Annual methane emissions per person, tonnes of CO2-equivalents per person (tCO2e/person).';
COMMENT ON COLUMN ghg_emissions.nitrous_oxide IS 'Annual nitrous oxide (N2O) emissions, million tonnes of CO2-equivalents (MtCO2e).';
COMMENT ON COLUMN ghg_emissions.nitrous_oxide_per_capita IS 'Annual nitrous oxide emissions per person, tonnes of CO2-equivalents per person (tCO2e/person).';
COMMENT ON COLUMN ghg_emissions.total_ghg IS 'Total greenhouse gas emissions including land-use change and forestry, million tonnes of CO2-equivalents (MtCO2e). Can be negative.';
COMMENT ON COLUMN ghg_emissions.total_ghg_excluding_lucf IS 'Total greenhouse gas emissions excluding land-use change and forestry, million tonnes of CO2-equivalents (MtCO2e).';
COMMENT ON COLUMN ghg_emissions.ghg_per_capita IS 'Total greenhouse gas emissions including land use per person, tonnes of CO2-equivalents per person (tCO2e/person).';
COMMENT ON COLUMN ghg_emissions.ghg_excluding_lucf_per_capita IS 'Total greenhouse gas emissions excluding land use per person, tonnes of CO2-equivalents per person (tCO2e/person).';
COMMENT ON COLUMN ghg_emissions.temperature_change_from_ghg IS 'Contribution to global mean surface temperature change from all greenhouse gases, degrees Celsius (°C).';
COMMENT ON COLUMN ghg_emissions.temperature_change_from_co2 IS 'Contribution to global temperature change from CO2, degrees Celsius (°C).';
COMMENT ON COLUMN ghg_emissions.temperature_change_from_ch4 IS 'Contribution to global temperature change from methane, degrees Celsius (°C).';
COMMENT ON COLUMN ghg_emissions.temperature_change_from_n2o IS 'Contribution to global temperature change from nitrous oxide, degrees Celsius (°C).';
COMMENT ON COLUMN ghg_emissions.share_of_temperature_change_from_ghg IS 'Share of global temperature change from greenhouse gases, percent (%).';

-- Primary keys already index (country_id, year). Year-first indexes serve
-- "all countries in year X" rankings; entity_type serves the country/aggregate filter.
CREATE INDEX IF NOT EXISTS country_indicators_year_idx ON country_indicators (year);
CREATE INDEX IF NOT EXISTS co2_emissions_year_idx ON co2_emissions (year);
CREATE INDEX IF NOT EXISTS ghg_emissions_year_idx ON ghg_emissions (year);
CREATE INDEX IF NOT EXISTS countries_entity_type_idx ON countries (entity_type);
