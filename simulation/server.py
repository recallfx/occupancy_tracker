import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import yaml
from aiohttp import web

# Add repository root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulation.sim_coordinator import SimOccupancyCoordinator
from simulation.layout import build_layout

# Configure logging
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    app = request.app
    coordinator = app["coordinator"]
    
    # Send initial config and layout
    await ws.send_json({
        "type": "init",
        "layout": app["layout"],
        "state": coordinator.data
    })
    
    # Listener for coordinator updates
    async def on_update():
        if ws.closed:
            return
        try:
            await ws.send_json({
                "type": "state_update",
                "state": coordinator.data
            })
        except Exception as exc:
            _LOGGER.debug("WebSocket update failed, closing connection: %s", exc)
            await ws.close()

    coordinator.async_add_listener(on_update)
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data["type"] == "sensor_event":
                    entity_id = data["entity_id"]
                    state = data["state"]
                    _LOGGER.info(f"Sensor event: {entity_id} -> {state}")
                    coordinator.process_sensor_event(entity_id, state, time.time())
                elif data["type"] == "reset_warnings":
                    _LOGGER.info("Received request to clear warnings")
                    coordinator.reset_warnings()
                elif data["type"] == "resolve_warning":
                    warning_id = data.get("warning_id")
                    if warning_id:
                        _LOGGER.info("Resolving warning %s", warning_id)
                        coordinator.resolve_warning(warning_id)
            elif msg.type == web.WSMsgType.ERROR:
                _LOGGER.error('ws connection closed with exception %s', ws.exception())
    except asyncio.CancelledError:
        _LOGGER.debug("WebSocket handler cancelled")
    finally:
        coordinator.async_remove_listener(on_update)
        if not ws.closed:
            await ws.close()

    return ws

async def index(request):
    # Serve index.html from the static directory
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

async def periodic_check(app):
    coordinator = app["coordinator"]
    try:
        while True:
            await asyncio.sleep(1)
            coordinator.check_timeouts(time.time())
    except asyncio.CancelledError:
        _LOGGER.debug("Periodic check task cancelled")
        # Don't re-raise, just exit cleanly
        return

async def start_background_tasks(app):
    app["periodic_task"] = asyncio.create_task(periodic_check(app))

async def cleanup_background_tasks(app):
    task = app.get("periodic_task")
    if not task:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

def main():
    config = load_config()
    coordinator = SimOccupancyCoordinator(config)
    layout = build_layout(config)
    
    app = web.Application()
    app["coordinator"] = coordinator
    app["layout"] = layout
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static", os.path.join(os.path.dirname(__file__), "static"))
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    web.run_app(app, port=8080)

if __name__ == "__main__":
    main()
