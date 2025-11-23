import { render } from './renderer.js';
import { createInputSystem } from './input.js';
import { runAutomation } from './automation.js';

// DOM Elements
const elements = {
    container: '#sim-container',
    statusBadge: document.getElementById('connectionStatus'),
    resetWarningsButton: document.getElementById('resetWarningsButton'),
    automationSelect: document.getElementById('automationSelect')
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

// WebSocket
const ws = new WebSocket('ws://' + window.location.host + '/ws');

ws.onopen = () => {
    elements.statusBadge.textContent = 'Connected';
    elements.statusBadge.className = 'status-badge connected';
    updateWarningControls();
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
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

elements.resetWarningsButton?.addEventListener('click', () => {
    if (!canSendToServer()) {
        return;
    }
    ws.send(JSON.stringify({ type: 'reset_warnings' }));
    elements.resetWarningsButton.disabled = true;
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
