---
layout: post
title: DaaSでサポートされているPostgreSQLの拡張機能をまとめてみた
tags:
  - PostgreSQL
  - "Azure Database"
  - "Amazon RDS"
  - "Google Cloud SQL"
---

|Extension|Amazon RDS for PostgreSQL|Google Cloud SQL for PostgreSQL|Azure Database for PostgreSQL|
|--------------------|----|----|
|address_standardizer|○||○|
|address_standardizer_data_us|○||○|
|ブルーム|○|||
|btree_gist|○|○|○|
|btree_gin|○|○|○|
|chkpass|○|○|○|
|citext |○|○|○|
|cube |○|○|○|
|dblink|○|||
|dict_int |○|○|○|
|dict_xsyn|○|○||
|earthdistance|○|○|○|
|fuzzystrmatch|○|○|○|
|hstore|○|○|○|
|hstore_plperl|○|||
|intagg|○|○||
|intarray|○|○|○|
|ip4r|○|||
|isn |○|○|○|
|lo||○||
|log_fdw|○|||
|ltree |○|○|○|
|orafce|○|||
|pgaudit|○|||
|pg_buffercache|○|○|○|
|pg_freespacemap|○|||
|pg_hint_plan|○|||
|pg_partman|||○|
|pg_prewarm|○|○|○|
|pg_repack |○|||
|pgrouting|||○|
|pg_stat_statements|○|○|○|
|pg_visibility|○|||
|pg_trgm|○|○|○|
|pgcrypto|○|○|○|
|pgrowlocks|○|○|○|
|pgrouting|||○|
|pgstattuple|○|○|○|
|plcoffee|○|||
|plls|○|||
|plperl|○|||
|plpgsql|○|○|○|
|pltcl|○|||
|plv8|○|||
|PostGIS|○|○|○|
|postgis_tiger_geocoder|○|○|○|
|postgis_topology|○|○|○|
|postgis_sfcgal|||○|
|postgres_fdw|○||○|
|postgresql-hll|○|||
|prefix|○|||
|sslinfo|○|○||
|tablefunc|○|○|○|
|test_parser|○|||
|tsearch2|○|||
|tsm_system_rows|○|○||
|tsm_system_time|○|○||
|unaccent |○|○|○|
|uuid-ossp||○||
