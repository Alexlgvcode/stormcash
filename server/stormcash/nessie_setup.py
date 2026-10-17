"""Create the guarantee pool in Nessie once (spec §11.4):

    python -m stormcash.nessie_setup [opening_dollars]

Creates a "StormCash Operator" customer with a "Guarantee Pool" account opened
at its full funding (default NESSIE_POOL_DOLLARS, $1000), records it as the
current pool (nessie_pool_accounts) and prints the line to add to server/.env.
Every demo reset then opens a fresh pool under the same customer.
"""

from __future__ import annotations

import sys

from .config import load_settings
from .db import make_pool
from .nessie import NessieClient, pool_account_id
from .sse import Broker


def main(argv: list[str]) -> None:
    settings = load_settings()
    dollars = int(argv[0]) if argv else settings.nessie_pool_dollars
    pool = make_pool(settings.database_url, max_size=2)
    with pool.connection() as conn:
        current = pool_account_id(conn, settings)
    if current:
        sys.exit(f"the guarantee pool already has a Nessie account ({current}); not creating another")
    nessie = NessieClient(settings.nessie_base_url, settings.nessie_api_key, pool, Broker())
    customer = nessie.create_customer("StormCash", "Operator")
    account = nessie.create_account(customer, "Guarantee Pool", dollars)
    with pool.connection() as conn:
        conn.execute("INSERT INTO nessie_pool_accounts (account_id, customer_id, opening_cents) VALUES (%s, %s, %s)",
                     (account, customer, dollars * 100))
    print(f"NESSIE_POOL_ACCOUNT_ID={account}")


if __name__ == "__main__":
    main(sys.argv[1:])
