"""手动验证富途连通/额度/历史/订阅。
前置: FutuOpenD 已登录运行。
用法: python scripts/check_futu.py HK.00700
"""
import sys
from futu import OpenQuoteContext, KLType, SubType, RET_OK


def main(code: str):
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        ret, quota = ctx.get_history_kl_quota(get_detail=True)
        print("== 历史K线额度 ==")
        print(quota if ret == RET_OK else f"FAIL: {quota}")

        ret, data, _ = ctx.request_history_kline(code, ktype=KLType.K_1M, max_count=5)
        print(f"== {code} 历史1分钟(前5) ==")
        print(data if ret == RET_OK else f"FAIL: {data}")

        ret, msg = ctx.subscribe([code], [SubType.K_1M])
        print("== 订阅1分钟 ==")
        print("OK" if ret == RET_OK else f"FAIL: {msg}")
        if ret == RET_OK:
            ret, cur = ctx.get_cur_kline(code, 3, KLType.K_1M)
            print(f"== {code} 当前1分钟(后3) ==")
            print(cur if ret == RET_OK else f"FAIL: {cur}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "HK.00700")