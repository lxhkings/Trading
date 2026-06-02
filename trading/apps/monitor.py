from __future__ import annotations
import os
import json
from pathlib import Path
import redis


def main():
    r = redis.Redis(host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    decode_responses=True)
    log_path = Path(os.environ.get("MONITOR_LOG", "data/monitor.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ps = r.pubsub()
    ps.psubscribe("fill.*", "alert", "signal.*")
    print(f"monitor running, logging -> {log_path}")
    with open(log_path, "a") as f:
        for msg in ps.listen():
            if msg.get("type") not in ("pmessage", "message"):
                continue
            rec = {"channel": msg["channel"], "data": msg["data"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if str(msg["channel"]).startswith("alert"):
                print(f"[ALERT] {msg['data']}")
            else:
                print(f"[{msg['channel']}] {msg['data']}")


if __name__ == "__main__":
    main()