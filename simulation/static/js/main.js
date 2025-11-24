import { render } from './renderer.js';
import { createInputSystem } from './input.js';
import { runAutomation } from './automation.js';
import { HistoryPlayer } from './history.js';

// DOM Elements
const elements = {
    container: '#sim-container',
    statusBadge: document.getElementById('connectionStatus'),
    resetWarningsButton: document.getElementById('resetWarningsButton'),
    automationSelect: document.getElementById('automationSelect'),
    historyButton: document.getElementById('historyButton'),
    historyCount: document.getElementById('historyCount'),
    verifyHistoryButton: document.getElementById('verifyHistoryButton')
};

const DEFAULT_DIMENSIONS = { width: 600, height: 500 };

// State
let layout = { areas: [], sensors: [], connections: [], dimensions: { ...DEFAULT_DIMENSIONS } };
let state = { areas: {}, sensors: {}, warnings: [] };
let persons = [
    { id: 1, x: 50, y: 50, dragging: false, radius: 15 },
    { id: 2, x: 100, y: 50, dragging: false, radius: 15 },
    { id: 3, x: 150, y: 50, dragging: false, radius: 15 }
];
let activeSensors = new Set();
let inputSystem = null;
let historyPlayer = null;

// WebSocket
const ws = new WebSocket('ws://' + window.location.host + '/ws');

ws.onopen = () => {
    elements.statusBadge.textContent = 'Connected';
    elements.statusBadge.className = 'status-badge connected';
    updateWarningControls();
    updateHistoryButton();
    
    // Initialize history player
    historyPlayer = new HistoryPlayer(ws, (historicalState) => {
        if (historicalState === null) {
            // Return to live mode - request fresh state
            console.log('[History] Exiting history mode, requesting live state');
            // The next WebSocket message will update us to live state
            return;
        }
        // Show historical state
        console.log('[History] Showing historical state at', new Date(historicalState.timestamp * 1000));
        state = historicalState;
        update();
    });
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('[WS] Received message:', data.type, 'history_count=', data.state?.history_count);
    
    // Always update history count, but skip state updates if in history mode
    if (data.state?.history_count !== undefined) {
        state.history_count = data.state.history_count;
        updateHistoryButton();
    }
    
    // Block state updates when viewing history
    if (historyPlayer && historyPlayer.isInHistoryMode()) {
        console.log('[WS] Ignoring update - in history mode');
        return;
    }
    
    if (data.type === 'init') {
        updateLayout(data.layout);
        state = data.state;
        update();
    } else if (data.type === 'state_update') {
        state = data.state;
        update();
    }
};

ws.onclose = () => {
    elements.statusBadge.textContent = 'Disconnected';
    elements.statusBadge.className = 'status-badge disconnected';
    updateWarningControls();
    updateHistoryButton();
};

function sendSensorEvent(entityId, state) {
    if (!canSendToServer()) {
        return;
    }
    ws.send(JSON.stringify({
        type: 'sensor_event',
        entity_id: entityId,
        state: state
    }));
}

function update() {
    if (!inputSystem) {
        inputSystem = createInputSystem(persons, layout, activeSensors, sendSensorEvent, update);
    }
    render(elements.container, layout, state, persons, activeSensors, elements, inputSystem.drag);
    updateWarningControls();
}

function updateLayout(newLayout) {
    layout.areas = newLayout.areas || [];
    layout.sensors = newLayout.sensors || [];
    layout.connections = newLayout.connections || [];
    layout.dimensions = newLayout.dimensions || layout.dimensions || { ...DEFAULT_DIMENSIONS };
    update();
}

function canSendToServer() {
    return ws.readyState === WebSocket.OPEN;
}

function updateWarningControls() {
    const hasWarnings = Array.isArray(state.warnings) && state.warnings.length > 0;
    const canSend = canSendToServer();

    if (elements.resetWarningsButton) {
        elements.resetWarningsButton.disabled = !(hasWarnings && canSend);
    }
}

function updateHistoryButton() {
    if (!elements.historyCount || !elements.historyButton) return;
    
    const historyCount = state.history_count || 0;
    console.log('[History] Updating button: count=', historyCount, 'canSend=', canSendToServer());
    elements.historyCount.textContent = historyCount;
    elements.historyButton.disabled = historyCount === 0 || !canSendToServer();
    
    if (elements.verifyHistoryButton) {
        elements.verifyHistoryButton.disabled = historyCount === 0 || !canSendToServer();
    }
}

elements.resetWarningsButton?.addEventListener('click', () => {
    if (!canSendToServer()) {
        return;
    }
    ws.send(JSON.stringify({ type: 'reset_warnings' }));
    elements.resetWarningsButton.disabled = true;
});

elements.historyButton?.addEventListener('click', () => {
    if (historyPlayer) {
        historyPlayer.enterHistoryMode();
    }
});

elements.verifyHistoryButton?.addEventListener('click', async () => {
    if (!canSendToServer()) {
        return;
    }
    
    elements.verifyHistoryButton.disabled = true;
    elements.verifyHistoryButton.textContent = '⏳ Verifying...';
    
    try {
        const response = await fetch('/api/verify_history', { method: 'POST' });
        const result = await response.json();
        
        if (result.passed) {
            elements.verifyHistoryButton.textContent = '✅ Passed!';
            console.log('✅ History verification passed');
        } else {
            elements.verifyHistoryButton.textContent = '❌ Failed';
            console.error('❌ History verification failed - check server logs');
        }
        
        // Reset button after 3 seconds
        setTimeout(() => {
            elements.verifyHistoryButton.textContent = '✓ Verify History';
            elements.verifyHistoryButton.disabled = state.history_count === 0;
        }, 3000);
    } catch (err) {
        console.error('Error verifying history:', err);
        elements.verifyHistoryButton.textContent = '❌ Error';
        setTimeout(() => {
            elements.verifyHistoryButton.textContent = '✓ Verify History';
            elements.verifyHistoryButton.disabled = state.history_count === 0;
        }, 3000);
    }
});

if (elements.automationSelect) {
    elements.automationSelect.addEventListener('change', async (event) => {
        console.log("Automation change event detected");
        const scenarioId = event.target.value;
        console.log("Selected scenario:", scenarioId);
        
        if (!scenarioId) return;
        
        if (!inputSystem) {
            console.warn("Input system not ready");
            return;
        }

        if (!layout.areas || layout.areas.length === 0) {
            console.warn("Layout not loaded yet");
            event.target.value = "";
            return;
        }

        event.target.disabled = true;

        try {
            console.log("Starting automation...");
            await runAutomation(scenarioId, persons, layout, inputSystem.checkSensors, update);
            console.log("Automation completed successfully");
        } catch (err) {
            console.error("Automation error:", err);
        } finally {
            event.target.disabled = false;
            event.target.value = ""; // Reset selection
        }
    });
} else {
    console.error("Automation select element not found in DOM");
}

// Initial render (empty)
update();
