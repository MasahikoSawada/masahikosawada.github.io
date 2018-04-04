---
layout: post
title: DaaSでサポートされているPostgreSQLの拡張機能をまとめてみた
tags:
  - PostgreSQL
  - "Azure Database"
  - "Amazon RDS"
  - "Cloud SQL"
  - Extension
---

PostgreSQLのDaaSを利用する時にどのような拡張機能が使えるかは重要で、少し気になったので現時点の状況を調べてみた。
対象は以下の3つ。

* Amazon RDS for PostgreSQL
  * PostgreSQL 10.1
  * URL: https://docs.aws.amazon.com/ja_jp/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html#PostgreSQL.Concepts.General.FeatureSupport.Extensions.101x
* Cloud SQL for PostgreSQL 
  * PostgreSQL 9.6（ベータ版）
  * URL: https://cloud.google.com/sql/docs/postgres/extensions?hl=ja
* Azure Database for PostgreSQL
  * PostgreSQL 9.6
  * URL: https://docs.microsoft.com/ja-jp/azure/postgresql/concepts-extensions


|拡張機能|Amazon RDS for PostgreSQL|Cloud SQL for PostgreSQL|Azure Database for PostgreSQL|
|--------------------|:----:|:----:|:-------:|
|address_standardizer|○||○|
|address_standardizer_data_us|○||○|
|auto_explain|○|||
|bloom|○|||
|btree_gist|○|○|○|
|btree_gin|○|○|○|
|chkpass|○|○|○|
|citext |○|○|○|
|cube |○|○|○|
|decoder_raw|○|||
|dblink|○|||
|dict_int |○|○|○|
|dict_xsyn|○|○||
|earthdistance|○|○|○|
|fuzzystrmatch|○|○|○|
|hstore|○|○|○|
|hstore_plperl|○|||
|ICU|○|||
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
|test_decoder|○|||
|tsearch2|○|||
|tsm_system_rows|○|○||
|tsm_system_time|○|○||
|unaccent |○|○|○|
|uuid-ossp||○||
|wal2json|○|||

※拡張機能はアルファベット順


使う拡張機能はどのDaasもサポートしている印象。

数が一番多いのはAmazon RDSで、pg_hint_planやpg_repack、orafceが使えるのはユーザにとって嬉しいかも。Azure Databaseは、他のサービスがサポートしていないpg_partmanやpgroutingとかをサポートしていて面白い。Cloud SQLはまだベータ版とのことなので、これからサポートする拡張機能が増えていくかもしれないので期待しています。
