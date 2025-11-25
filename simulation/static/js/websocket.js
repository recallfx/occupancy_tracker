/**
 * WebSocket connection management
 */

import { showToast } from './utils.js';

export class WebSocketManager {
    constructor(appState, onInit, onStateUpdate) {
        this.appState = appState;
        this.onInit = onInit;
        this.onStateUpdate = onStateUpdate;
        this.ws = null;
    }

    connect() {
        this.ws = new WebSocket('ws://' + window.location.host + '/ws');
        this.appState.ws = this.ws;
        this.setupHandlers();
        return this.ws;
    }

    setupHandlers() {
        this.ws.onopen = () => {
            showToast('Connected to simulation server', 'success');
            this.appState.updateUI();
            if (this.onStateUpdate) {
                this.onStateUpdate();
            }
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            // Handle log messages
            if (data.type === 'log') {
                this.handleLogMessage(data);
                return;
            }
            
            // Update history count
            if (data.state?.history_count !== undefined) {
                this.appState.state.history_count = data.state.history_count;
                this.appState.updateUI();
            }
            
            // Block state updates when viewing history
            if (this.appState.historyPlayer?.isInHistoryMode()) {
                return;
            }
            
            if (data.type === 'init') {
                this.appState.updateLayout(data.layout);
                this.appState.updateState(data.state);
                if (this.onInit) {
                    this.onInit();
                }
            } else if (data.type === 'state_update') {
                this.appState.updateState(data.state);
                if (this.onStateUpdate) {
                    this.onStateUpdate();
                }
            }
        };

        this.ws.onclose = () => {
            showToast('Connection lost', 'error', 5000);
            this.appState.updateUI();
        };
    }

    handleLogMessage(data) {
        const style = data.level === 'INFO' ? 'color: #03dac6' : 
                      data.level === 'WARNING' ? 'color: #f59e0b' : 
                      data.level === 'ERROR' ? 'color: #ef4444' : '';
        console.log(`%c${data.name}: ${data.message}`, style);
    }

    sendSensorEvent(entityId, state) {
        if (this.ws?.readyState !== WebSocket.OPEN) {
            return;
        }
        this.ws.send(JSON.stringify({
            type: 'sensor_event',
            entity_id: entityId,
            state: state
        }));
    }

    sendResetWarnings() {
        if (this.ws?.readyState !== WebSocket.OPEN) {
            showToast('Cannot reset warnings - not connected', 'error');
            return;
        }
        this.ws.send(JSON.stringify({ type: 'reset_warnings' }));
        showToast('Warnings reset', 'success');
    }
}
