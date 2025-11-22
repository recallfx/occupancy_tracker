import { formatTime } from './utils.js';

export function render(ctx, layout, state, person, activeSensors, elements) {
    drawMap(ctx, layout, state, person, activeSensors);
    renderAreas(layout, state, elements.areasGrid);
    renderSensors(state, elements.sensorsList);
    renderWarnings(state, elements.warningsList);
    updateSystemStats(state, elements);
}

function updateSystemStats(state, elements) {
    let total = 0;
    for (const area of Object.values(state.areas)) {
        total += area.occupancy;
    }
    elements.totalOccupancy.textContent = total;
    elements.activeWarningsCount.textContent = state.warnings.length;
}

function renderAreas(layout, state, container) {
    container.innerHTML = '';
    
    // Sort areas by ID for stability
    const sortedAreaIds = Object.keys(state.areas).sort();

    sortedAreaIds.forEach(areaId => {
        const areaData = state.areas[areaId];
        // layout.areas might not have all areas if config changed, fallback safely
        const areaConfig = layout.areas.find(a => a.id === areaId) || { name: areaId };
        
        const card = document.createElement('div');
        card.className = `area-card ${areaData.occupancy > 0 ? 'occupied' : ''}`;
        
        const probPercent = Math.round(areaData.probability * 100);
        
        card.innerHTML = `
            <div class="area-header">
                <span class="area-name">${areaId}</span>
                <span class="occupancy-count">${areaData.occupancy}</span>
            </div>
            <div class="stat-row">
                <span>Last Motion</span>
                <span>${formatTime(areaData.time_since_motion)}</span>
            </div>
            <div class="stat-row">
                <span>Probability</span>
                <span>${probPercent}%</span>
            </div>
            <div class="prob-bar-bg">
                <div class="prob-bar-fill" style="width: ${probPercent}%"></div>
            </div>
        `;
        container.appendChild(card);
    });
}

function renderSensors(state, container) {
    container.innerHTML = '';
    
    // Sort sensors
    const sortedSensorIds = Object.keys(state.sensors).sort();

    sortedSensorIds.forEach(sensorId => {
        const sensorData = state.sensors[sensorId];
        const shortName = sensorId.replace('motion_', '').replace('magnetic_', '').replace('person_', '');
        
        const item = document.createElement('div');
        item.className = `sensor-item ${sensorData.state ? 'active' : ''}`;
        
        item.innerHTML = `
            <div>
                <div class="sensor-name">${shortName}</div>
                <div class="sensor-meta">${sensorData.type}</div>
            </div>
            <div style="text-align: right">
                <div style="color: ${sensorData.state ? 'var(--secondary-color)' : 'var(--text-secondary)'}">
                    ${sensorData.state ? 'ON' : 'OFF'}
                </div>
                <div class="sensor-meta">${formatTime(sensorData.time_since_change)}</div>
            </div>
        `;
        container.appendChild(item);
    });
}

function renderWarnings(state, container) {
    container.innerHTML = '';
    
    if (state.warnings.length === 0) {
        container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.8rem; font-style: italic;">No active warnings</div>';
        return;
    }

    state.warnings.forEach(w => {
        const item = document.createElement('div');
        item.className = 'warning-item';
        const warningId = w.id || w.warning_id || '';
        item.innerHTML = `
            <div style="font-weight: bold; color: var(--error-color)">${w.type}</div>
            <div>${w.message}</div>
            <div class="sensor-meta">Area: ${w.area_id || 'N/A'}</div>
            <div class="warning-actions">
                <button class="ghost-button resolve-warning" data-warning-id="${warningId}">
                    Resolve
                </button>
            </div>
        `;
        container.appendChild(item);
    });
}

function getScale(ctx, layout) {
    const baseWidth = layout?.dimensions?.width || ctx.canvas.width || 1;
    const baseHeight = layout?.dimensions?.height || ctx.canvas.height || 1;
    return {
        x: ctx.canvas.width / baseWidth,
        y: ctx.canvas.height / baseHeight
    };
}

function drawMap(ctx, layout, state, person, activeSensors) {
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    const scale = getScale(ctx, layout);
    const areaCenters = new Map();

    // Draw Areas
    layout.areas.forEach(area => {
        // Check occupancy state
        const areaState = state.areas && state.areas[area.id];
        
        if (areaState && areaState.occupancy > 0) {
            ctx.fillStyle = '#ffcdd2'; // Red tint for occupied
            ctx.lineWidth = 3;
            ctx.strokeStyle = '#cf6679';
        } else {
            ctx.fillStyle = area.color;
            ctx.lineWidth = 1;
            ctx.strokeStyle = '#999';
        }

        const x = area.x * scale.x;
        const y = area.y * scale.y;
        const width = area.w * scale.x;
        const height = area.h * scale.y;

        ctx.fillRect(x, y, width, height);
        ctx.strokeRect(x, y, width, height);
        
        ctx.fillStyle = 'black';
        ctx.font = '12px Arial';
        ctx.fillText(area.id, x + 5, y + 20);

        areaCenters.set(area.id, {
            x: x + width / 2,
            y: y + height / 2
        });
    });

    drawConnections(ctx, layout.connections || [], areaCenters);

    // Draw Sensors
    layout.sensors.forEach(sensor => {
        const sensorX = sensor.x * scale.x;
        const sensorY = sensor.y * scale.y;
        ctx.beginPath();
        ctx.arc(sensorX, sensorY, 10, 0, Math.PI * 2);
        
        let color = 'gray';
        if (sensor.type === 'motion') color = 'blue';
        if (sensor.type === 'magnetic') color = 'green';
        if (sensor.type.includes('camera')) color = 'purple';
        
        // Highlight if active (person is on it)
        // Use the server state for visualization if available, otherwise local interaction
        const sensorState = state.sensors && state.sensors[sensor.id];
        const isActive = sensorState ? sensorState.state : activeSensors.has(sensor.id);

        if (isActive) {
            ctx.fillStyle = 'yellow';
            ctx.strokeStyle = color;
            ctx.lineWidth = 3;
        } else {
            ctx.fillStyle = color;
            ctx.strokeStyle = 'black';
            ctx.lineWidth = 1;
        }
        
        ctx.fill();
        ctx.stroke();
        
        ctx.fillStyle = 'black';
        ctx.font = '10px Arial';
        ctx.fillText(
            sensor.id.replace('motion_', '').replace('magnetic_', '').replace('person_', ''),
            sensorX - 10,
            sensorY - 15
        );
    });

    // Draw Person
    ctx.beginPath();
    ctx.arc(person.x, person.y, person.radius, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255, 0, 0, 0.7)';
    ctx.fill();
    ctx.strokeStyle = 'black';
    ctx.stroke();
}

function drawConnections(ctx, connections, areaCenters) {
    if (!connections.length) {
        return;
    }
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 6]);
    ctx.lineCap = 'round';

    connections.forEach(({ source, target }) => {
        const start = areaCenters.get(source);
        const end = areaCenters.get(target);
        if (!start || !end) {
            return;
        }
        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();
    });

    ctx.restore();
}
