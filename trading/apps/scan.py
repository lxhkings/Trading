from __future__ import annotations
import sys
import yaml
from trading.common.models import Market
from trading.feeds.futu_feed import FutuDataFeed
from trading.backtest.history import HistoryLoader
from trading.scanner.scanner import Scanner


def main(cfg_path: str, out_path: str):
    cfg = yaml.safe_load(open(cfg_path))
    feed = FutuDataFeed()
    feed.connect()
    try:
        loader = HistoryLoader(feed)
        sc = Scanner(loader,
                     min_turnover=cfg["min_turnover"],
                     min_atr_pct=cfg["min_atr_pct"])
        results = []
        for c in cfg["candidates"]:
            r = sc.scan_symbol(c["futu"], Market(c["market"]),
                               cfg["start"], cfg["end"], cfg["base_qty"])
            print(f"{r.symbol:12} sharpe={r.sharpe:+.3f} t_ret={r.t_return:+.4f} "
                  f"atr%={r.atr_pct:.4f} ac={r.autocorr:+.3f} "
                  f"turn={r.avg_turnover:,.0f} pass={r.passed_filters}")
            results.append(r)
        selected = sc.rank(results, top=cfg["top"])
        sc.export_yaml(selected, out_path)
        print(f"\nselected {len(selected)} -> {out_path}")
        for r in selected:
            print(f"  {r.market.value} {r.symbol} sharpe={r.sharpe:+.3f}")
    finally:
        feed.close()


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/candidates.yaml"
    out = sys.argv[2] if len(sys.argv) > 2 else "config/selected.yaml"
    main(cfg, out)