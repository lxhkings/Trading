from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
from trading.common.models import Bar, Order, Fill


class DataFeed(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def set_bar_handler(self, handler: Callable[[Bar], None]) -> None: ...

    @abstractmethod
    def subscribe(self, futu_symbols: list[str]) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class Broker(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def get_positions(self) -> dict[str, float]:
        """internal symbol -> 带符号持仓股数。"""

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """返回 order_id。"""

    @abstractmethod
    def cancel(self, order_id: str) -> None: ...

    @abstractmethod
    def set_fill_handler(self, handler) -> None: ...

    @abstractmethod
    def close(self) -> None: ...