from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
from trading.common.models import Bar


class DataFeed(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def set_bar_handler(self, handler: Callable[[Bar], None]) -> None: ...

    @abstractmethod
    def subscribe(self, futu_symbols: list[str]) -> None: ...

    @abstractmethod
    def close(self) -> None: ...