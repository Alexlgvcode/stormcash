"""Create the guarantee pool in Nessie once (spec §11.4):

    python -m stormcash.nessie_setup [opening_dollars]

Creates a "StormCash Operator" customer with a "Guarantee Pool" account opened
at its full funding (default $1000) and prints the line to add to server/.env.
"""

from __future__ import annotations

import sys

from .config import load_settings
from .db import make_pool
from .nessie import NessieClient
from .sse import Broker

DEFAULT_POOL_DOLLARS = 1000


def main(argv: list[str]) -> None:
    dollars = int(argv[0]) if argv else DEFAULT_POOL_DOLLARS
    settings = load_settings()
    if settings.nessie_pool_account_id:
        sys.exit(f"NESSIE_POOL_ACCOUNT_ID is already set ({settings.nessie_pool_account_id}); not creating another")
    pool = make_pool(settings.database_url, max_size=2)
    nessie = NessieClient(settings.nessie_base_url, settings.nessie_api_key, pool, Broker())
    customer = nessie.create_customer("StormCash", "Operator")
    account = nessie.create_account(customer, "Guarantee Pool", dollars)
    print(f"NESSIE_POOL_ACCOUNT_ID={account}")


if __name__ == "__main__":
    main(sys.argv[1:])
