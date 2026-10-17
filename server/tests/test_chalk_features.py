"""query_features over Chalk (spec §15.2), with a stand-in ChalkClient: no network."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from stormcash import chalk_features
from stormcash.stormdesk import tools

MID = "C482B122F2C1CC886A9949675DE8D98B"


class FakeError:
    def __init__(self, message: str) -> None:
        self.message = message


class FakeFeature:
    def __init__(self, field: str, value) -> None:
        self.field, self.value = field, value


class FakeResult:
    """Shaped like chalkpy's OnlineQueryResponseImpl: `data` (field, value) and `errors`."""

    def __init__(self, values: dict, errors: list | None = None) -> None:
        self.data = [FakeFeature(k, v) for k, v in values.items()]
        self.errors = errors or []


class FakeClient:
    def __init__(self, values: dict | None = None, errors: list | None = None, fail: Exception | None = None):
        self.values, self.errors, self.fail = values or {}, errors, fail
        self.calls: list[dict] = []

    def query(self, input, output, request_timeout=None):
        self.calls.append({"input": input, "output": output})
        if self.fail:
            raise self.fail
        return FakeResult(self.values, self.errors)


def test_query_asks_chalk_and_logs_latency(caplog):
    client = FakeClient({"merchant.as_of": 1792029600, "merchant.silence_ratio_6h": 0.1667,
                         "merchant.pool_funded_count_6h": 1})
    with caplog.at_level(logging.INFO, logger="stormcash.chalk_features"):
        out = chalk_features.query(None, "merchant", MID, ["silence_ratio_6h", "pool_funded_count_6h", "nope"],
                                   as_of=1792029600, client=client)
    assert client.calls == [{
        "input": {"merchant.id": MID.lower(), "merchant.as_of": 1792029600},
        "output": ["merchant.as_of", "merchant.silence_ratio_6h", "merchant.pool_funded_count_6h"],
    }]
    assert out["source"] == "chalk" and out["as_of"] == 1792029600
    assert out["features"] == {"silence_ratio_6h": 0.1667, "pool_funded_count_6h": 1}
    assert out["unknown_features"] == ["nope"] and isinstance(out["latency_ms"], int)
    assert "chalk query merchant c482b122" in caplog.text and "silence_ratio_6h, pool_funded_count_6h" in caplog.text


def test_query_defaults_to_every_feature_of_the_entity():
    client = FakeClient({"certificate.as_of": 5})
    out = chalk_features.query(None, "cert", "ab" * 16, client=client)
    assert client.calls[0]["input"] == {"certificate.id": "ab" * 16}
    assert client.calls[0]["output"][1:] == [f"certificate.{f}" for f in chalk_features.FEATURES["cert"]]
    assert set(out["features"]) == set(chalk_features.FEATURES["cert"])


def test_query_raises_when_chalk_cannot_answer():
    with pytest.raises(chalk_features.ChalkUnavailable, match="ConnectionError"):
        chalk_features.query(None, "region", "swannanoa", client=FakeClient(fail=ConnectionError("down")))
    with pytest.raises(chalk_features.ChalkUnavailable, match="source not found"):
        chalk_features.query(None, "region", "swannanoa", ["active_certs"],
                             client=FakeClient(errors=[FakeError("source not found")]))


def test_tool_uses_chalk_then_falls_back(deps, monkeypatch):
    # Tests build Settings directly, so Chalk is off and the tool reads Postgres.
    off = tools.call(deps, "query_features", {"entity": "region", "id": "swannanoa"})
    assert off["source"] == "postgres_fallback" and "CHALK_DISABLED" in off["chalk_error"]

    deps.settings = dataclasses.replace(deps.settings, chalk_enabled=True)
    monkeypatch.setattr(chalk_features, "_client", FakeClient({"region.as_of": 7, "region.active_certs": 57}))
    on = tools.call(deps, "query_features", {"entity": "region", "id": "swannanoa", "features": ["active_certs"]})
    assert on == {"source": "chalk", "entity": "region", "id": "swannanoa", "as_of": 7,
                  "features": {"active_certs": 57}, "latency_ms": on["latency_ms"]}

    monkeypatch.setattr(chalk_features, "_client", FakeClient(fail=TimeoutError("slow")))
    down = tools.call(deps, "query_features", {"entity": "region", "id": "swannanoa"})
    assert down["source"] == "postgres_fallback" and "TimeoutError" in down["chalk_error"]
