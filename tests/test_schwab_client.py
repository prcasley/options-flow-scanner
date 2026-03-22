"""Unit tests for the Schwab/TD Ameritrade API client."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.sources.schwab_client import SchwabAuthError, SchwabClient


@pytest.fixture
def client(tmp_path):
    return SchwabClient(
        client_id="test_key",
        client_secret="test_secret",
        redirect_uri="https://127.0.0.1",
        token_file=str(tmp_path / "tokens.json"),
    )


@pytest.fixture
def authenticated_client(tmp_path):
    token_file = tmp_path / "tokens.json"
    tokens = {
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "token_expiry": time.time() + 3600,
    }
    token_file.write_text(json.dumps(tokens))
    return SchwabClient(
        client_id="test_key",
        client_secret="test_secret",
        redirect_uri="https://127.0.0.1",
        token_file=str(token_file),
    )


class TestSchwabAuth:
    def test_get_auth_url_contains_client_id(self, client):
        url = client.get_auth_url()
        assert "test_key" in url
        assert "https://api.schwabapi.com" in url
        assert "response_type=code" in url

    def test_load_tokens_from_file(self, tmp_path):
        token_file = tmp_path / "tokens.json"
        expiry = time.time() + 3600
        token_file.write_text(
            json.dumps(
                {
                    "access_token": "acc",
                    "refresh_token": "ref",
                    "token_expiry": expiry,
                }
            )
        )
        c = SchwabClient("key", "secret", token_file=str(token_file))
        assert c._access_token == "acc"
        assert c._refresh_token == "ref"

    def test_missing_token_file_no_error(self, tmp_path):
        c = SchwabClient("k", "s", token_file=str(tmp_path / "nope.json"))
        assert c._access_token is None

    @pytest.mark.asyncio
    async def test_exchange_code_stores_tokens(self, client, tmp_path):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "access_token": "new_acc",
                "refresh_token": "new_ref",
                "expires_in": 1800,
            }
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("scanner.sources.schwab_client.aiohttp.ClientSession") as cls:
            cls.return_value = mock_session
            client._session = mock_session
            await client.exchange_code("some_code")

        assert client._access_token == "new_acc"
        assert Path(client.token_file).exists()

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_error(self, client):
        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="Unauthorized")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)

        client._session = mock_session
        with pytest.raises(SchwabAuthError):
            await client.exchange_code("bad_code")

    @pytest.mark.asyncio
    async def test_ensure_token_raises_without_auth(self, client):
        client._access_token = None
        client._refresh_token = None
        client._token_expiry = time.time() - 1
        with pytest.raises(SchwabAuthError):
            await client._ensure_token()


class TestSchwabNormalise:
    def test_normalise_chain_call(self, client):
        raw = {
            "callExpDateMap": {
                "2025-06-20:90": {
                    "150.0": [
                        {
                            "totalVolume": 500,
                            "openInterest": 1200,
                            "last": 3.5,
                            "volatility": 30.0,
                            "delta": 0.6,
                            "gamma": 0.02,
                            "theta": -0.05,
                            "vega": 0.1,
                            "bid": 3.4,
                            "ask": 3.6,
                        }
                    ]
                }
            },
            "putExpDateMap": {},
        }
        results = client._normalise_chain("AAPL", raw)
        assert len(results) == 1
        c = results[0]
        assert c["details"]["contract_type"] == "call"
        assert c["details"]["strike_price"] == 150.0
        assert c["details"]["expiration_date"] == "2025-06-20"
        assert c["day"]["volume"] == 500
        assert c["open_interest"] == 1200
        assert c["greeks"]["implied_volatility"] == pytest.approx(0.3)

    def test_normalise_chain_put(self, client):
        raw = {
            "callExpDateMap": {},
            "putExpDateMap": {
                "2025-06-20:90": {
                    "140.0": [
                        {
                            "totalVolume": 200,
                            "openInterest": 800,
                            "last": 2.0,
                            "volatility": None,
                            "bid": 1.9,
                            "ask": 2.1,
                        }
                    ]
                }
            },
        }
        results = client._normalise_chain("AAPL", raw)
        assert len(results) == 1
        assert results[0]["details"]["contract_type"] == "put"
        assert results[0]["greeks"]["implied_volatility"] is None

    def test_normalise_empty_chain(self, client):
        results = client._normalise_chain("AAPL", {})
        assert results == []

    def test_contract_to_snapshot_structure(self):
        snap = SchwabClient._contract_to_snapshot(
            "AAPL",
            "2025-06-20",
            "call",
            150.0,
            {"totalVolume": 100, "openInterest": 50, "last": 2.0},
        )
        assert "details" in snap
        assert "day" in snap
        assert "greeks" in snap
        assert "open_interest" in snap
        assert snap["source"] == "schwab"


class TestSchwabExtendedHours:
    def test_is_extended_hours_returns_bool(self):
        result = SchwabClient.is_extended_hours()
        assert isinstance(result, bool)

    def test_name(self, client):
        assert client.name == "schwab"
