-- depends_on: {{ source('lake', 'ledger_entries') }}
select * from {{ all_batches('ledger_entries') }}
