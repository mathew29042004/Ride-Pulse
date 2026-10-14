-- Double-entry bookkeeping: every ledger transaction's entries must sum to exactly zero.
select transaction_id, sum(amount) as imbalance
from {{ ref('stg_ledger_entries') }}
group by transaction_id
having sum(amount) <> 0
