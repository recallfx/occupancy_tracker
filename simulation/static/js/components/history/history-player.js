/**
 * History playback module for occupancy tracker simulation
 */

import { showToast } from '../../utils.js';

export class HistoryPlayer {
    constructor(ws, onStateChange, historyControlsElement) {
        this.ws = ws;
        this.onStateChange = onStateChange;
        this.historyControlsElement = historyControlsElement;
        this.history = [];
        this.currentIndex = 0;
        this.isPlaying = false;
        this.playInterval = null;
        this.isHistoryMode = false;
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
            
            this.currentIndex = this.history.length - 1;
            return true;
        } catch (err) {
            console.error('Failed to load history:', err);
            return false;
        }
    }
    
    async enterHistoryMode() {
        const loaded = await this.loadHistory();
        if (!loaded) {
            showToast('No history available to replay', 'warning');
            return false;
        }
        
        this.isHistoryMode = true;
        this.showSnapshot(this.currentIndex);
        this.updateControls();
        
        if (this.historyControlsElement) {
            this.historyControlsElement.visible = true;
        }
        
        return true;
    }
    
    exitHistoryMode() {
        this.isHistoryMode = false;
        this.stopPlayback();
        
        if (this.historyControlsElement) {
            this.historyControlsElement.visible = false;
        }
        
        // Request current live state
        if (this.onStateChange) {
            this.onStateChange(null); // Signal to return to live mode
        }
    }
    
    updateControls() {
        if (!this.historyControlsElement) return;
        
        this.historyControlsElement.currentIndex = this.currentIndex;
        this.historyControlsElement.totalCount = this.history.length;
        this.historyControlsElement.isPlaying = this.isPlaying;
        
        const snapshot = this.history[this.currentIndex];
        if (snapshot) {
            const date = new Date(snapshot.timestamp * 1000);
            const timeStr = date.toLocaleTimeString();
            const desc = snapshot.description || 'System tick';
            this.historyControlsElement.timestamp = `${timeStr} - ${desc}`;
        }
    }
    
    showSnapshot(index) {
        if (index < 0 || index >= this.history.length) return;
        
        const snapshot = this.history[index];
        this.currentIndex = index;
        
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
        
        if (this.onStateChange) {
            this.onStateChange(state);
        }
    }
    
    stepForward() {
        if (this.currentIndex < this.history.length - 1) {
            this.showSnapshot(this.currentIndex + 1);
        }
        this.updateControls();
    }
    
    stepBackward() {
        if (this.currentIndex > 0) {
            this.showSnapshot(this.currentIndex - 1);
        }
        this.updateControls();
    }
    
    togglePlayback() {
        if (this.isPlaying) {
            this.stopPlayback();
        } else {
            this.startPlayback();
        }
        this.updateControls();
    }
    
    startPlayback() {
        this.isPlaying = true;
        this.updateControls();
        
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
        this.updateControls();
        
        if (this.playInterval) {
            clearInterval(this.playInterval);
            this.playInterval = null;
        }
    }
    
    seekTo(index) {
        if (index >= 0 && index < this.history.length) {
            this.showSnapshot(index);
            this.updateControls();
        }
    }
    
    cleanup() {
        this.stopPlayback();
    }
    
    isInHistoryMode() {
        return this.isHistoryMode;
    }
}
