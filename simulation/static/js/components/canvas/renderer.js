import { formatTime } from '../../utils.js';

const d3 = window.d3;

export function render(containerElement, layout, state, persons, activeSensors, elements, dragBehavior) {
    // Handle both selector strings and DOM elements
    const container = typeof containerElement === 'string' 
        ? d3.select(containerElement) 
        : d3.select(containerElement);
    const width = layout.dimensions?.width || 800;
    const height = layout.dimensions?.height || 600;

    let svg = container.select('svg');
    if (svg.empty()) {
        svg = container.append('svg')
            .attr('viewBox', `0 0 ${width} ${height}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .style('width', '100%')
            .style('height', '100%')
            .style('background', 'white')
            .style('display', 'block');
            
        svg.append('g').attr('class', 'areas-layer');
        svg.append('g').attr('class', 'connections-layer');
        svg.append('g').attr('class', 'sensors-layer');
        svg.append('g').attr('class', 'person-layer');
        svg.append('g').attr('class', 'hud-layer');
        svg.append('g').attr('class', 'warnings-layer');
    } else {
        svg.attr('viewBox', `0 0 ${width} ${height}`);
    }

    drawMap(svg, layout, state, persons, activeSensors, dragBehavior);
    drawHUD(svg, state, width, height);
    drawWarningsOverlay(svg, state, width, height);
}

function drawHUD(svg, state, width, height) {
    const hudLayer = svg.select('.hud-layer');
    
    // Calculate stats
    let totalOccupancy = 0;
    for (const area of Object.values(state.areas)) {
        totalOccupancy += area.occupancy;
    }
    const activeWarnings = state.warnings.length;

    // Background for HUD
    let bg = hudLayer.select('.hud-bg');
    if (bg.empty()) {
        bg = hudLayer.append('rect')
            .attr('class', 'hud-bg')
            .attr('rx', 5)
            .attr('ry', 5)
            .attr('fill', 'rgba(255, 255, 255, 0.85)')
            .attr('stroke', '#ccc')
            .attr('stroke-width', 1);
    }

    const hudWidth = 180;
    const hudHeight = 55;
    const margin = 10;
    const xPos = width - hudWidth - margin;
    const yPos = margin;

    bg.attr('x', xPos)
      .attr('y', yPos)
      .attr('width', hudWidth)
      .attr('height', hudHeight);

    const hudData = [
        { label: 'Total Occupancy:', value: totalOccupancy, x: xPos + 10, y: yPos + 20 },
        { label: 'Active Warnings:', value: activeWarnings, x: xPos + 10, y: yPos + 40, alert: activeWarnings > 0 }
    ];

    const hudGroup = hudLayer.selectAll('.hud-stats').data([0]);
    const hudGroupEnter = hudGroup.enter().append('g').attr('class', 'hud-stats');
    
    // We just redraw the text content
    const texts = hudLayer.selectAll('.hud-text')
        .data(hudData);

    texts.enter().append('text')
        .attr('class', 'hud-text')
        .attr('font-family', 'Arial')
        .attr('font-size', '14px')
        .attr('font-weight', 'bold')
        .merge(texts)
        .attr('x', d => d.x)
        .attr('y', d => d.y)
        .attr('fill', d => d.alert ? 'red' : 'black')
        .text(d => `${d.label} ${d.value}`);

    texts.exit().remove();
}

function drawWarningsOverlay(svg, state, width, height) {
    const warningsLayer = svg.select('.warnings-layer');
    
    if (state.warnings.length === 0) {
        warningsLayer.selectAll('*').remove();
        return;
    }

    // Draw a semi-transparent box at the bottom right or top right for warnings
    const boxWidth = 300;
    const boxHeight = state.warnings.length * 20 + 30;
    const x = width - boxWidth - 10;
    const y = 75; // Below the HUD (55 height + 10 margin + 10 spacing)

    let bg = warningsLayer.select('.warnings-bg');
    if (bg.empty()) {
        bg = warningsLayer.append('rect')
            .attr('class', 'warnings-bg')
            .attr('rx', 5)
            .attr('ry', 5)
            .attr('fill', 'rgba(255, 255, 255, 0.9)')
            .attr('stroke', 'red')
            .attr('stroke-width', 1);
    }
    
    bg.attr('x', x)
      .attr('y', y)
      .attr('width', boxWidth)
      .attr('height', boxHeight);

    const title = warningsLayer.selectAll('.warnings-title').data([0]);
    title.enter().append('text')
        .attr('class', 'warnings-title')
        .attr('font-family', 'Arial')
        .attr('font-size', '12px')
        .attr('font-weight', 'bold')
        .attr('fill', 'red')
        .merge(title)
        .attr('x', x + 10)
        .attr('y', y + 20)
        .text('Active Warnings:');

    const warningTexts = warningsLayer.selectAll('.warning-text')
        .data(state.warnings);

    warningTexts.enter().append('text')
        .attr('class', 'warning-text')
        .attr('font-family', 'Arial')
        .attr('font-size', '10px')
        .merge(warningTexts)
        .attr('x', x + 10)
        .attr('y', (d, i) => y + 40 + (i * 15))
        .attr('fill', '#333')
        .text(d => `${d.type}: ${d.message} (${d.area_id || 'Global'})`);

    warningTexts.exit().remove();
}

function drawMap(svg, layout, state, persons, activeSensors, dragBehavior) {
    // Areas
    const areasLayer = svg.select('.areas-layer');
    const areas = areasLayer.selectAll('.area')
        .data(layout.areas, d => d.id);

    const areasEnter = areas.enter().append('g')
        .attr('class', 'area');
    
    areasEnter.append('rect');
    areasEnter.append('text');

    const areasMerge = areasEnter.merge(areas);

    // Color scale for occupancy probability/density
    // Use blue scale for probability to distinguish from red occupied state
    const probabilityScale = d3.scaleSequential(d3.interpolateBlues).domain([0, 1]);

    areasMerge.select('rect')
        .attr('x', d => d.x)
        .attr('y', d => d.y)
        .attr('width', d => d.w)
        .attr('height', d => d.h)
        .attr('fill', d => {
            const areaState = state.areas && state.areas[d.id];
            if (!areaState) return d.color || '#eee';
            
            // If occupied, use a distinct color or high intensity
            if (areaState.occupancy > 0) {
                // A solid color for confirmed occupancy
                return '#ffcdd2'; 
            }
            
            // If not occupied but has probability, use the blue scale
            if (areaState.probability > 0) {
                return probabilityScale(areaState.probability);
            }
            
            return d.color || '#f5f5f5';
        })
        .attr('stroke', d => {
            const areaState = state.areas && state.areas[d.id];
            return (areaState && areaState.occupancy > 0) ? '#cf6679' : '#999';
        })
        .attr('stroke-width', d => {
            const areaState = state.areas && state.areas[d.id];
            return (areaState && areaState.occupancy > 0) ? 3 : 1;
        });

    const areaText = areasMerge.select('text')
        .attr('x', d => d.x + 5)
        .attr('y', d => d.y + 20)
        .attr('font-family', 'Arial')
        .attr('font-size', '12px')
        .attr('fill', 'black')
        .style('paint-order', 'stroke')
        .style('stroke', 'white')
        .style('stroke-width', '3px')
        .style('stroke-linecap', 'butt')
        .style('stroke-linejoin', 'miter');
    
    // Clear existing tspans to redraw
    areaText.text(null);
    
    // Area ID
    areaText.append('tspan')
        .attr('x', d => d.x + 5)
        .attr('dy', 0)
        .attr('font-weight', 'bold')
        .text(d => d.id);

    // Occupancy
    areaText.append('tspan')
        .attr('x', d => d.x + 5)
        .attr('dy', '1.2em')
        .attr('font-size', '11px')
        .text(d => {
            const areaState = state.areas && state.areas[d.id];
            return areaState ? `Occ: ${areaState.occupancy}` : '';
        });

    // Probability
    areaText.append('tspan')
        .attr('x', d => d.x + 5)
        .attr('dy', '1.1em')
        .attr('font-size', '10px')
        .attr('fill', '#555')
        .text(d => {
            const areaState = state.areas && state.areas[d.id];
            if (!areaState) return '';
            const prob = Math.round(areaState.probability * 100);
            return `Prob: ${prob}%`;
        });
        
    // Last Motion
    areaText.append('tspan')
        .attr('x', d => d.x + 5)
        .attr('dy', '1.1em')
        .attr('font-size', '10px')
        .attr('fill', '#555')
        .text(d => {
            const areaState = state.areas && state.areas[d.id];
            if (!areaState) return '';
            return `Last: ${formatTime(areaState.time_since_motion)}`;
        });

    areas.exit().remove();

    // Connections
    const areaCenters = new Map();
    layout.areas.forEach(area => {
        areaCenters.set(area.id, {
            x: area.x + area.w / 2,
            y: area.y + area.h / 2
        });
    });

    const connectionsLayer = svg.select('.connections-layer');
    const connections = connectionsLayer.selectAll('.connection')
        .data((layout.connections || []).filter(d => areaCenters.has(d.source) && areaCenters.has(d.target)));

    connections.enter().append('line')
        .attr('class', 'connection')
        .attr('stroke', 'rgba(0, 0, 0, 0.45)')
        .attr('stroke-width', 2)
        .attr('stroke-dasharray', '8, 6')
        .attr('stroke-linecap', 'round')
        .merge(connections)
        .attr('x1', d => areaCenters.get(d.source)?.x || 0)
        .attr('y1', d => areaCenters.get(d.source)?.y || 0)
        .attr('x2', d => areaCenters.get(d.target)?.x || 0)
        .attr('y2', d => areaCenters.get(d.target)?.y || 0);

    connections.exit().remove();

    // Sensors
    const sensorsLayer = svg.select('.sensors-layer');
    const sensors = sensorsLayer.selectAll('.sensor')
        .data(layout.sensors, d => d.id);

    const sensorsEnter = sensors.enter().append('g')
        .attr('class', 'sensor');
    
    sensorsEnter.append('circle')
        .attr('r', 10);
    
    // Add cooldown ring for motion sensors
    sensorsEnter.append('circle')
        .attr('class', 'cooldown-ring')
        .attr('r', 14)
        .attr('fill', 'none')
        .attr('stroke-width', 2)
        .attr('opacity', 0);
    
    sensorsEnter.append('text')
        .attr('class', 'sensor-name')
        .attr('text-anchor', 'end')
        .attr('font-family', 'Arial')
        .attr('font-size', '10px')
        .attr('fill', 'black')
        .style('paint-order', 'stroke')
        .style('stroke', 'white')
        .style('stroke-width', '3px')
        .style('stroke-linecap', 'butt')
        .style('stroke-linejoin', 'miter');

    sensorsEnter.append('text')
        .attr('class', 'sensor-state')
        .attr('text-anchor', 'start')
        .attr('font-family', 'Arial')
        .attr('font-size', '9px')
        .style('paint-order', 'stroke')
        .style('stroke', 'white')
        .style('stroke-width', '3px')
        .style('stroke-linecap', 'butt')
        .style('stroke-linejoin', 'miter');

    const sensorsMerge = sensorsEnter.merge(sensors);

    // Patch existing nodes
    sensorsMerge.select('text').attr('class', 'sensor-name')
        .style('paint-order', 'stroke')
        .style('stroke', 'white')
        .style('stroke-width', '3px')
        .style('stroke-linecap', 'butt')
        .style('stroke-linejoin', 'miter');

    sensorsMerge.each(function() {
        if (d3.select(this).select('.sensor-state').empty()) {
             d3.select(this).append('text')
                .attr('class', 'sensor-state')
                .attr('text-anchor', 'start')
                .attr('font-family', 'Arial')
                .attr('font-size', '9px')
                .style('paint-order', 'stroke')
                .style('stroke', 'white')
                .style('stroke-width', '3px')
                .style('stroke-linecap', 'butt')
                .style('stroke-linejoin', 'miter');
        }
    });

    sensorsMerge.attr('transform', d => `translate(${d.x}, ${d.y})`);

    sensorsMerge.select('circle')
        .attr('fill', d => {
            const sensorState = state.sensors && state.sensors[d.id];
            const isActive = sensorState ? sensorState.state : activeSensors.has(d.id);
            if (isActive) return 'yellow';
            if (d.type === 'motion') return 'blue';
            if (d.type === 'magnetic') return 'green';
            if (d.type.includes('camera')) return 'purple';
            return 'gray';
        })
        .attr('stroke', d => {
            const sensorState = state.sensors && state.sensors[d.id];
            const isActive = sensorState ? sensorState.state : activeSensors.has(d.id);
            if (isActive) {
                if (d.type === 'motion') return 'blue';
                if (d.type === 'magnetic') return 'green';
                if (d.type.includes('camera')) return 'purple';
            }
            return 'black';
        })
        .attr('stroke-width', d => {
            const sensorState = state.sensors && state.sensors[d.id];
            const isActive = sensorState ? sensorState.state : activeSensors.has(d.id);
            return isActive ? 3 : 1;
        });

    // Update cooldown ring for motion sensors
    sensorsMerge.select('.cooldown-ring')
        .attr('stroke', d => {
            if (d.type === 'motion') return 'orange';
            if (d.type === 'magnetic') return 'green';
            if (d.type.includes('camera')) return 'purple';
            return 'gray';
        })
        .attr('opacity', d => {
            // Show cooldown ring when sensor is in timeout
            if (activeSensors.has(d.id + '_cooldown')) return 0.6;
            return 0;
        });

    sensorsMerge.select('.sensor-name')
        .attr('x', -12)
        .attr('y', -5)
        .text(d => d.id.replace('motion_', '').replace('magnetic_', '').replace('person_', ''));

    sensorsMerge.select('.sensor-state')
        .attr('x', 12)
        .attr('y', 4)
        .text(d => {
            const sensorState = state.sensors && state.sensors[d.id];
            if (!sensorState) return '';
            return sensorState.state ? 'ON' : 'OFF';
        })
        .attr('fill', d => {
            const sensorState = state.sensors && state.sensors[d.id];
            return (sensorState && sensorState.state) ? 'black' : '#999';
        })
        .attr('font-weight', d => {
            const sensorState = state.sensors && state.sensors[d.id];
            return (sensorState && sensorState.state) ? 'bold' : 'normal';
        });

    sensors.exit().remove();

    // Person
    const personLayer = svg.select('.person-layer');
    const personNode = personLayer.selectAll('.person')
        .data(persons, d => d.id);

    personNode.enter().append('circle')
        .attr('class', 'person')
        .attr('r', d => d.radius)
        .attr('fill', 'rgba(255, 0, 0, 0.7)')
        .attr('stroke', 'black')
        .attr('cursor', 'grab')
        .call(dragBehavior)
        .merge(personNode)
        .attr('cx', d => d.x)
        .attr('cy', d => d.y);
        
    personNode.exit().remove();
}