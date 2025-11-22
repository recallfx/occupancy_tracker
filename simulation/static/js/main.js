import { render } from './renderer.js';
import { setupInput } from './input.js';

// DOM Elements
const elements = {
    canvas: document.getElementById('simCanvas'),
    statusBadge: document.getElementById('connectionStatus'),
    areasGrid: document.getElementById('areasGrid'),
    sensorsList: document.getElementById('sensorsList'),
    warningsList: document.getElementById('warningsList'),
    totalOccupancy: document.getElementById('totalOccupancy'),
    activeWarningsCount: document.getElementById('activeWarningsCount'),
    resetWarningsButton: document.getElementById('resetWarningsButton'),
    sidebarToggle: document.getElementById('sidebarToggle')
};

const DEFAULT_DIMENSIONS = { width: 600, height: 500 };
const ctx = elements.canvas.getContext('2d');

// State
let layout = { areas: [], sensors: [], connections: [], dimensions: { ...DEFAULT_DIMENSIONS } };
let state = { areas: {}, sensors: {}, warnings: [] };
let person = { x: 50, y: 50, dragging: false, radius: 15 };
let activeSensors = new Set();
let sidebarPreference = null; // null follows responsive breakpoints

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
    render(ctx, layout, state, person, activeSensors, elements);
    updateWarningControls();
}

function updateLayout(newLayout) {
    layout.areas = newLayout.areas || [];
    layout.sensors = newLayout.sensors || [];
    layout.connections = newLayout.connections || [];
    layout.dimensions = newLayout.dimensions || layout.dimensions || { ...DEFAULT_DIMENSIONS };
    resizeCanvas({ redraw: false });
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

    const resolveButtons = elements.warningsList?.querySelectorAll('.resolve-warning') || [];
    resolveButtons.forEach((button) => {
        const hasId = Boolean(button.dataset.warningId);
        button.disabled = !(hasId && canSend);
    });
}

function getBaseDimensions() {
    const dims = layout.dimensions || DEFAULT_DIMENSIONS;
    return {
        width: dims.width || DEFAULT_DIMENSIONS.width,
        height: dims.height || DEFAULT_DIMENSIONS.height
    };
}

function clampPersonToCanvas(canvasWidth, canvasHeight) {
    person.x = Math.min(Math.max(person.radius, person.x), canvasWidth - person.radius);
    person.y = Math.min(Math.max(person.radius, person.y), canvasHeight - person.radius);
}

function resizeCanvas(options = {}) {
    const { redraw = true } = options;
    const container = elements.canvas.parentElement;
    const baseDims = getBaseDimensions();
    const measuredWidth = container?.clientWidth || 0;
    const fallbackWidth = window.innerWidth || baseDims.width;
    const availableWidth = measuredWidth > 0 ? measuredWidth : Math.max(240, fallbackWidth);
    const targetWidth = Math.round(Math.min(availableWidth, 1000));
    const aspectRatio = baseDims.height / baseDims.width || 1;
    const targetHeight = Math.round(targetWidth * aspectRatio);

    const widthChanged = elements.canvas.width !== targetWidth;
    const heightChanged = elements.canvas.height !== targetHeight;

    if (widthChanged || heightChanged) {
        elements.canvas.width = targetWidth;
        elements.canvas.height = targetHeight;
        clampPersonToCanvas(targetWidth, targetHeight);
        if (redraw) {
            update();
        }
    }
}

function applySidebarState() {
    const autoCollapse = window.innerWidth < 900;
    const shouldCollapse = sidebarPreference === null ? autoCollapse : sidebarPreference;
    document.body.classList.toggle('sidebar-hidden', shouldCollapse);
}

elements.resetWarningsButton?.addEventListener('click', () => {
    if (!canSendToServer()) {
        return;
    }
    ws.send(JSON.stringify({ type: 'reset_warnings' }));
    elements.resetWarningsButton.disabled = true;
});

elements.warningsList?.addEventListener('click', (event) => {
    const button = event.target.closest('.resolve-warning');
    if (!button) {
        return;
    }
    const warningId = button.dataset.warningId;
    if (!warningId || !canSendToServer()) {
        return;
    }
    button.disabled = true;
    ws.send(JSON.stringify({ type: 'resolve_warning', warning_id: warningId }));
});

elements.sidebarToggle?.addEventListener('click', () => {
    const currentlyCollapsed = document.body.classList.contains('sidebar-hidden');
    sidebarPreference = !currentlyCollapsed;
    applySidebarState();
});

// Setup Input
setupInput(
    elements.canvas, 
    person, 
    layout, 
    activeSensors, 
    sendSensorEvent, 
    update
);

resizeCanvas({ redraw: false });
applySidebarState();
window.addEventListener('resize', () => {
    resizeCanvas();
    if (sidebarPreference === null && window.innerWidth >= 900) {
        document.body.classList.remove('sidebar-hidden');
    } else {
        applySidebarState();
    }
});

// Initial render (empty)
update();
