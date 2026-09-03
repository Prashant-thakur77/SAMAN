"""A tiny TCP forwarder, for one job: let containers reach an Ollama that
listens only on the host's loopback, without changing the host's service.

Runs with network_mode: host, binds on the Docker bridge address only (so the
port is reachable from containers and from the host, never from the LAN) and
forwards every connection to 127.0.0.1:11434.

    python tcp-bridge.py <bind-host> <bind-port> <target-host> <target-port>
"""

import asyncio
import sys


async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def handle(client_reader, client_writer, target_host: str, target_port: int) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(target_host, target_port)
    except OSError:
        client_writer.close()
        return
    await asyncio.gather(
        pump(client_reader, upstream_writer),
        pump(upstream_reader, client_writer),
    )


async def main(bind_host: str, bind_port: int, target_host: str, target_port: int) -> None:
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, target_host, target_port), bind_host, bind_port
    )
    print(f"bridge {bind_host}:{bind_port} -> {target_host}:{target_port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    host, port, thost, tport = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    asyncio.run(main(host, port, thost, tport))
