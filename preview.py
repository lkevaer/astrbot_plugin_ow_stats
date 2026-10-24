"""Generate a synthetic, offline long-image preview from the bundled web UI."""

import argparse
import asyncio
import struct
from pathlib import Path

from render import WebRenderer
from tests.fixtures import make_report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--output", type=Path, default=Path("output/preview.png"))
    args = parser.parse_args()
    renderer = WebRenderer()
    try:
        png = await renderer.render(make_report(args.players))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(png)
        width, height = struct.unpack(">II", png[16:24])
        print(
            f"Synthetic preview: {args.output.resolve()} ({width} x {height}, {len(png)} bytes)"
        )
    finally:
        await renderer.close()


if __name__ == "__main__":
    asyncio.run(main())
