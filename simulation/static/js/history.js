/**
 * History playback module for occupancy tracker simulation
 */

export class HistoryPlayer {
    constructor(ws, onStateChange) {
        this.ws = ws;
        this.onStateChange = onStateChange;
        this.history = [];
        this.currentIndex = 0;
        this.isPlaying = false;
        this.playInterval = null;
        this.isHistoryMode = false;
        
        this.setupControls();
    }
    
    setupControls() {
        this.controls = document.getElementById('historyControls');
        this.slider = document.getElementById('historySlider');
        this.playPauseBtn = document.getElementById('historyPlayPause');
        this.exitBtn = document.getElementById('exitHistoryButton');
        this.infoSpan = document.getElementById('historyInfo');
        this.timestampSpan = document.getElementById('historyTimestamp');
        
        this.slider.addEventListener('input', (e) => {
            this.currentIndex = parseInt(e.target.value);
            this.showSnapshot(this.currentIndex);
        });
        
        this.playPauseBtn.addEventListener('click', () => {
            this.togglePlayback();
        });
        
        this.exitBtn.addEventListener('click', () => {
            this.exitHistoryMode();
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (!this.isHistoryMode) return;
            
            switch(e.key) {
                case 'ArrowLeft':
                    e.preventDefault();
                    this.stepBackward();
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    this.stepForward();
                    break;
                case ' ':
                    e.preventDefault();
                    this.togglePlayback();
                    break;
                case 'Escape':
                    e.preventDefault();
                    this.exitHistoryMode();
                    break;
            }
        });
    }
    
    async loadHistory() {
        try {
            const response = await fetch('/api/history');
            const data = await response.json();
            this.history = data.history;
            
            if (this.history.length === 0) {
                console.log('No history available');
                return false;
            }
            
            this.slider.max = this.history.length - 1;
            this.slider.value = this.history.length - 1;
            this.currentIndex = this.history.length - 1;
            
            this.updateInfo();
            return true;
        } catch (err) {
            console.error('Failed to load history:', err);
            return false;
        }
    }
    
    async enterHistoryMode() {
        const loaded = await this.loadHistory();
        if (!loaded) {
            alert('No history available to replay');
            return;
        }
        
        this.isHistoryMode = true;
        this.controls.style.display = 'block';
        this.showSnapshot(this.currentIndex);
    }
    
    exitHistoryMode() {
        this.isHistoryMode = false;
        this.stopPlayback();
        this.controls.style.display = 'none';
        
        // Request current live state
        if (this.onStateChange) {
            this.onStateChange(null); // Signal to return to live mode
        }
    }
    
    showSnapshot(index) {
        if (index < 0 || index >= this.history.length) return;
        
        const snapshot = this.history[index];
        this.currentIndex = index;
        this.slider.value = index;
        
        // Convert snapshot to simulation state format
        const state = {
            areas: {},
            sensors: {},
            warnings: [],
            timestamp: snapshot.timestamp,
            isHistorical: true
        };
        
        // Convert area data
        for (const [areaId, areaData] of Object.entries(snapshot.areas)) {
            state.areas[areaId] = {
                occupancy: areaData.occupancy || 0,
                probability: areaData.occupancy > 0 ? 1.0 : 0.0,
                last_motion: areaData.last_motion || 0,
                time_since_motion: areaData.last_motion ? 
                    snapshot.timestamp - areaData.last_motion : null,
                is_indoors: areaData.is_indoors !== false,
                is_exit_capable: areaData.is_exit_capable === true
            };
        }
        
        // Convert sensor data
        for (const [sensorId, sensorData] of Object.entries(snapshot.sensors)) {
            state.sensors[sensorId] = {
                state: sensorData.state || false,
                last_changed: sensorData.last_changed || 0,
                time_since_change: sensorData.last_changed ?
                    snapshot.timestamp - sensorData.last_changed : null,
                type: sensorData.type || 'motion',
                is_stuck: false
            };
        }
        
        this.updateInfo();
        this.updateTimestamp(snapshot);
        
        if (this.onStateChange) {
            this.onStateChange(state);
        }
    }
    
    updateInfo() {
        this.infoSpan.textContent = `${this.currentIndex + 1} / ${this.history.length}`;
    }
    
    updateTimestamp(snapshot) {
        const date = new Date(snapshot.timestamp * 1000);
        const timeStr = date.toLocaleTimeString();
        const desc = snapshot.description || 'System tick';
        this.timestampSpan.textContent = `${timeStr} - ${desc}`;
    }
    
    stepForward() {
        if (this.currentIndex < this.history.length - 1) {
            this.showSnapshot(this.currentIndex + 1);
        }
    }
    
    stepBackward() {
        if (this.currentIndex > 0) {
            this.showSnapshot(this.currentIndex - 1);
        }
    }
    
    togglePlayback() {
        if (this.isPlaying) {
            this.stopPlayback();
        } else {
            this.startPlayback();
        }
    }
    
    startPlayback() {
        this.isPlaying = true;
        this.playPauseBtn.textContent = '⏸️';
        
        this.playInterval = setInterval(() => {
            if (this.currentIndex < this.history.length - 1) {
                this.stepForward();
            } else {
                this.stopPlayback();
            }
        }, 500); // 500ms per snapshot
    }
    
    stopPlayback() {
        this.isPlaying = false;
        this.playPauseBtn.textContent = '▶️';
        
        if (this.playInterval) {
            clearInterval(this.playInterval);
            this.playInterval = null;
        }
    }
    
    cleanup() {
        this.stopPlayback();
    }
    
    isInHistoryMode() {
        return this.isHistoryMode;
    }
}
