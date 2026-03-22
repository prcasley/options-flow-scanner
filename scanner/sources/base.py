"""Abstract base class for data source clients."""

from abc import ABC, abstractmethod


class DataSource(ABC):
    """Base interface for options data providers."""

    @abstractmethod
    async def get_options_snapshot(self, underlying: str) -> list[dict]:
        """Fetch all options contracts snapshot for a ticker.

        Returns a list of raw contract dicts in a normalised format.
        Each dict should have at minimum:
          details.strike_price, details.expiration_date, details.contract_type,
          day.volume, open_interest
        """

    @abstractmethod
    async def get_most_active(self) -> list[str]:
        """Return a list of the most active underlying tickers for discovery."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable source identifier."""

    async def close(self):
        """Release any held resources (sessions, connections, etc.)."""
