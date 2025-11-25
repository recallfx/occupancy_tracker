/**
 * Event handling and coordination
 */

import { runAutomation } from './components/app/automation.js';
import { verifyHistory } from './api.js';

export class EventCoordinator {
    constructor(appState, wsManager, update) {
        this.appState = appState;
        this.wsManager = wsManager;
        this.update = update;
        this.setupEventListeners();
    }

    setupEventListeners() {
        // Canvas ready
        document.addEventListener('canvas-ready', () => {
            console.log('Canvas ready event received');
            setTimeout(() => this.update(), 50);
        });
        
        // Scenario automation
        document.addEventListener('scenario-selected', (e) => {
            this.handleScenarioSelected(e.detail.scenario);
        });

        // Warnings management
        document.addEventListener('reset-warnings', () => {
            this.wsManager.sendResetWarnings();
        });

        // History controls
        document.addEventListener('history-open', () => {
            this.handleHistoryOpen();
        });

        document.addEventListener('history-exit', () => {
            this.handleHistoryExit();
        });

        document.addEventListener('history-step-back', () => {
            this.appState.historyPlayer?.stepBackward();
        });

        document.addEventListener('history-step-forward', () => {
            this.appState.historyPlayer?.stepForward();
        });

        document.addEventListener('history-play-pause', () => {
            this.appState.historyPlayer?.togglePlayback();
        });

        document.addEventListener('history-seek', (e) => {
            this.appState.historyPlayer?.seekTo(e.detail.index);
        });

        document.addEventListener('verify-history', () => {
            verifyHistory();
        });

        // Keyboard shortcuts for history
        document.addEventListener('keydown', (e) => {
            if (!this.appState.historyPlayer?.isInHistoryMode()) return;
            
            switch(e.key) {
                case 'ArrowLeft':
                    e.preventDefault();
                    this.appState.historyPlayer?.stepBackward();
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    this.appState.historyPlayer?.stepForward();
                    break;
                case ' ':
                    e.preventDefault();
                    this.appState.historyPlayer?.togglePlayback();
                    break;
                case 'Escape':
                    e.preventDefault();
                    this.handleHistoryExit();
                    break;
            }
        });
    }

    async handleScenarioSelected(scenario) {
        if (!scenario || !this.appState.inputSystem) return;
        if (!this.appState.layout.areas || this.appState.layout.areas.length === 0) return;

        try {
            await runAutomation(
                scenario,
                this.appState.persons,
                this.appState.layout,
                this.appState.inputSystem.checkSensors,
                this.update
            );
        } catch (err) {
            console.error("Automation error:", err);
        }
    }

    async handleHistoryOpen() {
        if (this.appState.historyPlayer) {
            await this.appState.historyPlayer.enterHistoryMode();
        }
    }

    handleHistoryExit() {
        if (this.appState.historyPlayer) {
            this.appState.historyPlayer.exitHistoryMode();
        }
    }
}
