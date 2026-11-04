"""Falso `claude`: grava args e stdin, imprime a fixture de stream-json."""
import json
import os
import sys
from pathlib import Path

here = Path(__file__).parent
log = os.environ.get("FAKE_CLAUDE_LOG")
if os.environ.get("FAKE_CLAUDE_PIDFILE"):
    Path(os.environ["FAKE_CLAUDE_PIDFILE"]).write_text(str(os.getpid()))
stdin = sys.stdin.read()
if log:
    Path(log).write_text(json.dumps({"args": sys.argv[1:], "stdin": stdin, "env": dict(os.environ)}), encoding="utf-8")
print("linha que não é json")
sys.stdout.write((here / os.environ.get("FAKE_CLAUDE_FIXTURE", "claude_stream.jsonl")).read_text(encoding="utf-8"))
sys.stdout.flush()
if os.environ.get("FAKE_CLAUDE_SLEEP"):
    import time
    time.sleep(float(os.environ["FAKE_CLAUDE_SLEEP"]))
if os.environ.get("FAKE_CLAUDE_EXIT"):
    sys.stderr.write("deu ruim no claude\n")
    sys.exit(int(os.environ["FAKE_CLAUDE_EXIT"]))
