{# The newest snapshot of a lake table (extract.py keeps a few dated snapshots). #}
{% macro latest_snapshot(table) %}
(
    with files as (
        select *, regexp_extract(filename, 'snapshot=([^/]+)', 1) as _snapshot
        from read_parquet('{{ var("lake_path") }}/{{ table }}/snapshot=*/data.parquet', filename = true)
    )
    select * exclude (filename, _snapshot)
    from files
    where _snapshot = (select max(_snapshot) from files)
)
{% endmacro %}

{# All incremental batches of an append-only table, one row per id. #}
{% macro all_batches(table) %}
(
    select * exclude (filename)
    from read_parquet('{{ var("lake_path") }}/{{ table }}/batch=*/data.parquet', filename = true)
    qualify row_number() over (partition by id order by filename desc) = 1
)
{% endmacro %}

{# UTC timestamp -> Indian Standard Time (no daylight saving, so a fixed zone is exact). #}
{% macro ist(column) %}({{ column }} AT TIME ZONE 'Asia/Kolkata'){% endmacro %}

{# Write staging/core/reporting schemas as named (not prefixed with the target schema). #}
{% macro generate_schema_name(custom_schema_name, node) %}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{% endmacro %}
