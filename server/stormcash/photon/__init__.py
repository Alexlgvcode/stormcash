"""Photon messaging agent (spec §17, WS7): merchant notices and appeals over Telegram.

Wire-in (WS2 owns app.py):

    from .photon import routes as photon
    app.include_router(photon.router)

and call `notices.hold_notice(deps, flag_id)` when an operator approves `hold_pool_payout` or
`lower_merchant_limit`, and `notices.settled_notice(deps, payout_id)` when a payout is executed.
"""
