/**
 * Main application entry point - minimal orchestration layer
 */

import './components/index.js';
import { render } from './components/canvas/renderer.js';
import { createInputSystem } from './components/canvas/input.js';
import { HistoryPlayer } from './components/history/history-player.js';
import { AppState } from './state.js';
import { WebSocketManager } from './websocket.js';
import { EventCoordinator } from './events.js';
import { DOMInitializer } from './dom.js';

// Global application state
const appState = new AppState();

// WebSocket manager
const wsManager = new WebSocketManager(
    appState,
    () => update(),  // onInit
    () => update()   // onStateUpdate
);

// Core update function - renders the simulation state
function update() {
    if (!appState.inputSystem && appState.container) {
        appState.inputSystem = createInputSystem(
            appState.persons,
            appState.layout,
            appState.activeSensors,
            (entityId, state) => wsManager.sendSensorEvent(entityId, state),
            update
        );
    }
    
    if (appState.container) {
        render(
            appState.container,
            appState.layout,
            appState.state,
            appState.persons,
            appState.activeSensors,
            {},
            appState.inputSystem?.drag
        );
    }
    
    appState.updateUI();
}

// Initialize the application
function start() {
    // Initialize event coordinator
    new EventCoordinator(appState, wsManager, update);
    
    // Initialize DOM and start when ready
    new DOMInitializer(appState, () => {
        // Initialize history player
        appState.historyPlayer = new HistoryPlayer(
            appState.ws,
            (historicalState) => {
                if (historicalState === null) {
                    return;
                }
                appState.updateState(historicalState);
                update();
            },
            appState.historyControlsElement
        );
        
        // Connect WebSocket
        wsManager.connect();
        
        // Start rendering
        update();
    });
}

// Start the application
start();
