export async function runAutomation(scenarioId, persons, layout, checkSensors, renderCallback) {
    // Define scenarios
    const scenarios = {
        scenario1: ['frontyard', 'magnetic_entry', 'entrance', 'front_hall', 'back_hall', 'main_bedroom', 'main_bathroom', 'main_bedroom'],
        scenario2: ['frontyard', 'magnetic_entry', 'entrance', 'front_hall', 'back_hall', 'main_bedroom', 'main_bathroom']
    };

    const path = scenarios[scenarioId];
    if (!path) {
        console.warn(`Scenario ${scenarioId} not found`);
        return;
    }

    // Pick a person based on scenario
    // Scenario 1 -> Person 1 (index 0)
    // Scenario 2 -> Person 2 (index 1)
    let personIndex = 0;
    if (scenarioId === 'scenario2') personIndex = 1;
    if (personIndex >= persons.length) personIndex = 0; // fallback

    const person = persons[personIndex];
    console.log(`Starting automation ${scenarioId} with person ${person.id}`);

    for (const targetId of path) {
        let targetX, targetY;
        
        // Check if target is an area
        const area = layout.areas.find(a => a.id === targetId);
        if (area) {
            targetX = area.x + area.w / 2;
            targetY = area.y + area.h / 2;
        } else {
            // Check if target is a sensor
            const sensor = layout.sensors.find(s => s.id === targetId);
            if (sensor) {
                targetX = sensor.x;
                targetY = sensor.y;
            }
        }

        if (targetX !== undefined && targetY !== undefined) {
            console.log(`Moving to ${targetId} at (${targetX}, ${targetY})`);
            // "Walks quite fast" -> interpolate over 200ms (was 500ms)
            await animateMove(person, targetX, targetY, 200, checkSensors, renderCallback);
            
            // "stays 0.5s in one room" (was 2s)
            await wait(500);
        } else {
            console.warn(`Target ${targetId} not found in layout`);
        }
    }
    console.log(`Automation ${scenarioId} finished`);
}

function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function animateMove(person, targetX, targetY, duration, checkSensors, renderCallback) {
    const startX = person.x;
    const startY = person.y;
    const startTime = performance.now();

    return new Promise(resolve => {
        function step(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);

            // Linear interpolation
            person.x = startX + (targetX - startX) * progress;
            person.y = startY + (targetY - startY) * progress;

            checkSensors();
            renderCallback();

            if (progress < 1) {
                requestAnimationFrame(step);
            } else {
                resolve();
            }
        }
        requestAnimationFrame(step);
    });
}
