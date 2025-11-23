const d3 = window.d3;

export function createInputSystem(persons, layout, activeSensors, sendEventCallback, renderCallback) {
    
    const sensorTimeouts = new Map();

    function checkSensors() {
        layout.sensors.forEach(sensor => {
            let isOverlapping = false;
            for (const p of persons) {
                const dx = p.x - sensor.x;
                const dy = p.y - sensor.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                
                // Sensor radius 10 + Person radius 15 = 25
                if (dist < 25) {
                    isOverlapping = true;
                    break;
                }
            }
            
            if (isOverlapping) {
                // Motion detected: Cancel any pending off-timer
                if (sensorTimeouts.has(sensor.id)) {
                    clearTimeout(sensorTimeouts.get(sensor.id));
                    sensorTimeouts.delete(sensor.id);
                    // Re-trigger event to notify backend of re-entry/continued motion
                    sendEventCallback(sensor.id, true);
                }

                // Turn on immediately if not already on
                if (!activeSensors.has(sensor.id)) {
                    activeSensors.add(sensor.id);
                    sendEventCallback(sensor.id, true);
                }
            } else {
                // No motion/contact
                if (activeSensors.has(sensor.id)) {
                    if (sensor.type === 'magnetic') {
                        // Magnetic sensors turn off immediately
                        activeSensors.delete(sensor.id);
                        sendEventCallback(sensor.id, false);
                    } else if (!sensorTimeouts.has(sensor.id)) {
                        // Motion sensors have a cooldown
                        const timeoutId = setTimeout(() => {
                            activeSensors.delete(sensor.id);
                            sendEventCallback(sensor.id, false);
                            sensorTimeouts.delete(sensor.id);
                            renderCallback(); // Update UI when sensor turns off
                        }, 1500);
                        sensorTimeouts.set(sensor.id, timeoutId);
                    }
                }
            }
        });
    }

    const drag = d3.drag()
        .on("start", (event, d) => {
            d.dragging = true;
            d3.select(event.sourceEvent.target).attr("cursor", "grabbing");
        })
        .on("drag", (event, d) => {
            const width = layout.dimensions?.width || 800;
            const height = layout.dimensions?.height || 600;
            
            d.x = Math.max(d.radius, Math.min(width - d.radius, event.x));
            d.y = Math.max(d.radius, Math.min(height - d.radius, event.y));
            
            checkSensors();
            renderCallback();
        })
        .on("end", (event, d) => {
            d.dragging = false;
            d3.select(event.sourceEvent.target).attr("cursor", "grab");
        });

    return { drag, checkSensors };
}
