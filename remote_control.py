"""Interactive REST client for the Pan-Tilt head.

Usage:  python remote_control.py [--host 192.168.1.76] [--port 8080]
Type ? at the prompt for commands.
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request

HELP = """  p <deg>      absolute pan
  t <deg>      absolute tilt
  pt <p> <t>   both
  h | hp | ht  home both / pan / tilt
  d            stop and de-energize motors (axes become unhomed)
  s            state
  q            quit"""

HOME = {"h": "both", "hp": "pan", "ht": "tilt"}
MOVE = {"p": ("pan",), "t": ("tilt",), "pt": ("pan", "tilt")}


def call(base, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def build(name, args):
    if name == "s" and not args:
        return "state", None
    if name == "d" and not args:
        return "disable", {}
    if name in HOME and not args:
        return "home", {"axis": HOME[name]}
    if name in MOVE and len(args) == len(MOVE[name]):
        return "move", dict(zip(MOVE[name], map(float, args)))
    raise ValueError("Unknown command or wrong arguments; ? for help")


def describe(state):
    text = "pan={} tilt={} busy={}".format(state["pan"], state["tilt"], state["busy"])
    return text + " error={}".format(state["error"]) if state["error"] else text


def wait_idle(base):
    try:
        while True:
            time.sleep(0.1)
            state = call(base, "state")[1]
            if not state["busy"]:
                print("done: " + describe(state))
                return
    except KeyboardInterrupt:
        print("(no longer waiting; motion continues, use d to stop)")


def main():
    parser = argparse.ArgumentParser(description="Pan-tilt REST remote control")
    parser.add_argument("--host", default=os.environ.get("PAN_TILT_HOST", "pan-tilt-head.local"),
                        help="hostname or IP address (default: pan-tilt-head.local)")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    base = "http://{}:{}/api/v1/".format(args.host, args.port)

    try:
        print(describe(call(base, "state")[1]))
    except OSError as error:
        print(error)
        return

    while True:
        try:
            line = input("rc> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "q":
            break
        if line == "?":
            print(HELP)
            continue
        name, *words = line.split()
        try:
            path, payload = build(name, words)
            started = time.perf_counter()
            status, result = call(base, path, payload)
            print("{} [{} in {:.0f} ms]".format(
                describe(result), status, (time.perf_counter() - started) * 1000))
            if status == 202:
                wait_idle(base)
        except (ValueError, OSError) as error:
            print(error)


if __name__ == "__main__":
    main()
