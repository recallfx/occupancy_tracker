export function setupInput(canvas, person, layout, activeSensors, sendEventCallback, renderCallback) {
    function getScale() {
        const baseWidth = layout?.dimensions?.width || canvas.width;
        const baseHeight = layout?.dimensions?.height || canvas.height;
        return {
            x: canvas.width / baseWidth,
            y: canvas.height / baseHeight
        };
    }

    function clampToCanvas(x, y) {
        const clampedX = Math.min(Math.max(person.radius, x), canvas.width - person.radius);
        const clampedY = Math.min(Math.max(person.radius, y), canvas.height - person.radius);
        return { x: clampedX, y: clampedY };
    }

    function pointerPosition(clientX, clientY) {
        const rect = canvas.getBoundingClientRect();
        return {
            x: clientX - rect.left,
            y: clientY - rect.top
        };
    }

    function checkSensors() {
        const { x: scaleX, y: scaleY } = getScale();
        layout.sensors.forEach(sensor => {
            const sensorX = sensor.x * scaleX;
            const sensorY = sensor.y * scaleY;
            const dx = person.x - sensorX;
            const dy = person.y - sensorY;
            const dist = Math.sqrt(dx * dx + dy * dy);
            
            // Sensor radius 10 + Person radius 15 = 25
            const isOverlapping = dist < 25;
            
            if (isOverlapping && !activeSensors.has(sensor.id)) {
                activeSensors.add(sensor.id);
                sendEventCallback(sensor.id, true);
            } else if (!isOverlapping && activeSensors.has(sensor.id)) {
                activeSensors.delete(sensor.id);
                sendEventCallback(sensor.id, false);
            }
        });
    }

    function startInteraction(x, y) {
        const { x: px, y: py } = clampToCanvas(x, y);
        const dx = px - person.x;
        const dy = py - person.y;
        if (Math.sqrt(dx * dx + dy * dy) < person.radius) {
            person.dragging = true;
        } else {
            person.x = px;
            person.y = py;
            checkSensors();
            renderCallback();
        }
    }

    function dragInteraction(x, y) {
        if (!person.dragging) return;
        const { x: px, y: py } = clampToCanvas(x, y);
        person.x = px;
        person.y = py;
        checkSensors();
        renderCallback();
    }

    function endInteraction() {
        person.dragging = false;
    }

    // Mouse Events
    canvas.addEventListener('mousedown', (e) => {
        const { x, y } = pointerPosition(e.clientX, e.clientY);
        startInteraction(x, y);
    });

    canvas.addEventListener('mousemove', (e) => {
        const { x, y } = pointerPosition(e.clientX, e.clientY);
        dragInteraction(x, y);
    });

    canvas.addEventListener('mouseup', endInteraction);
    canvas.addEventListener('mouseleave', endInteraction);

    // Touch Events
    canvas.addEventListener('touchstart', (e) => {
        if (!e.touches.length) return;
        const touch = e.touches[0];
        const { x, y } = pointerPosition(touch.clientX, touch.clientY);
        startInteraction(x, y);
        e.preventDefault();
    }, { passive: false });

    canvas.addEventListener('touchmove', (e) => {
        if (!e.touches.length) return;
        const touch = e.touches[0];
        const { x, y } = pointerPosition(touch.clientX, touch.clientY);
        dragInteraction(x, y);
        e.preventDefault();
    }, { passive: false });

    canvas.addEventListener('touchend', endInteraction);
    canvas.addEventListener('touchcancel', endInteraction);
}
