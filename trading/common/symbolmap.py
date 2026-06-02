from __future__ import annotations
from dataclasses import dataclass
from trading.common.models import Market


@dataclass(frozen=True)
class SymbolSpec:
    internal: str
    futu: str
    ib_symbol: str
    ib_exchange: str
    ib_currency: str
    market: Market


class SymbolMap:
    def __init__(self, specs: list[SymbolSpec]):
        self._by_internal = {s.internal: s for s in specs}
        self._by_futu = {s.futu: s for s in specs}

    def by_internal(self, code: str) -> SymbolSpec:
        return self._by_internal[code]

    def by_futu(self, code: str) -> SymbolSpec:
        return self._by_futu[code]

    def all_futu(self) -> list[str]:
        return list(self._by_futu.keys())

    @classmethod
    def from_yaml(cls, path: str) -> "SymbolMap":
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f)
        specs = [
            SymbolSpec(
                internal=e["internal"], futu=e["futu"],
                ib_symbol=str(e["ib_symbol"]), ib_exchange=e["ib_exchange"],
                ib_currency=e["ib_currency"], market=Market(e["market"]),
            )
            for e in raw["symbols"]
        ]
        return cls(specs)