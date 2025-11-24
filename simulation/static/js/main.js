import { render } from './renderer.js';
import { createInputSystem } from './input.js';
import { runAutomation } from './automation.js';
import { HistoryPlayer } from './history.js';
import { showToast } from './utils.js';

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
    showToast('Connected to simulation server', 'success');
    updateWarningControls();
    updateHistoryButton();
    
    // Initialize history player
    historyPlayer = new HistoryPlayer(ws, (historicalState) => {
        if (historicalState === null) {
            // Return to live mode - request fresh state
            return;
        }
        // Show historical state
        state = historicalState;
        update();
    });
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    // Handle log messages from server
    if (data.type === 'log') {
        const style = data.level === 'INFO' ? 'color: #03dac6' : 
                      data.level === 'WARNING' ? 'color: #f59e0b' : 
                      data.level === 'ERROR' ? 'color: #ef4444' : '';
        console.log(`%c${data.name}: ${data.message}`, style);
        return;
    }
    
    // Always update history count, but skip state updates if in history mode
    if (data.state?.history_count !== undefined) {
        state.history_count = data.state.history_count;
        updateHistoryButton();
    }
    
    // Block state updates when viewing history
    if (historyPlayer && historyPlayer.isInHistoryMode()) {
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
    showToast('Connection lost', 'error', 5000);
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
    elements.historyCount.textContent = historyCount;
    elements.historyButton.disabled = historyCount === 0 || !canSendToServer();
    
    if (elements.verifyHistoryButton) {
        elements.verifyHistoryButton.disabled = historyCount === 0 || !canSendToServer();
    }
}

elements.resetWarningsButton?.addEventListener('click', () => {
    if (!canSendToServer()) {
        showToast('Cannot reset warnings - not connected', 'error');
        return;
    }
    ws.send(JSON.stringify({ type: 'reset_warnings' }));
    elements.resetWarningsButton.disabled = true;
    showToast('Warnings reset', 'success');
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
            showToast('History verification passed', 'success');
        } else {
            elements.verifyHistoryButton.textContent = '❌ Failed';
            console.error('❌ History verification failed - check server logs');
            showToast('History verification failed - check logs', 'error');
        }
        
        // Reset button after 3 seconds
        setTimeout(() => {
            elements.verifyHistoryButton.textContent = '✓ Verify History';
            elements.verifyHistoryButton.disabled = state.history_count === 0;
        }, 3000);
    } catch (err) {
        console.error('Error verifying history:', err);
        elements.verifyHistoryButton.textContent = '❌ Error';
        showToast('Error verifying history', 'error');
        setTimeout(() => {
            elements.verifyHistoryButton.textContent = '✓ Verify History';
            elements.verifyHistoryButton.disabled = state.history_count === 0;
        }, 3000);
    }
});

if (elements.automationSelect) {
    elements.automationSelect.addEventListener('change', async (event) => {
        const scenarioId = event.target.value;
        
        if (!scenarioId) return;
        
        if (!inputSystem) {
            return;
        }

        if (!layout.areas || layout.areas.length === 0) {
            event.target.value = "";
            return;
        }

        event.target.disabled = true;

        try {
            await runAutomation(scenarioId, persons, layout, inputSystem.checkSensors, update);
        } catch (err) {
            console.error("Automation error:", err);
        } finally {
            event.target.disabled = false;
            event.target.value = ""; // Reset selection
        }
    });
}

// Initial render (empty)
update();
