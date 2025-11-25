/**
 * DOM initialization and setup
 */

export class DOMInitializer {
    constructor(appState, onReady) {
        this.appState = appState;
        this.onReady = onReady;
        this.init();
    }

    init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.findElements());
        } else {
            this.findElements();
        }
    }

    findElements() {
        this.appState.appElement = document.querySelector('occupancy-sim-app');
        
        if (!this.appState.appElement) {
            setTimeout(() => this.findElements(), 100);
            return;
        }
        
        // Wait for shadow DOM to be ready
        setTimeout(() => {
            this.appState.historyControlsElement = this.appState.appElement?.shadowRoot?.querySelector('history-controls');
            this.appState.canvasElement = this.appState.appElement?.shadowRoot?.querySelector('sim-canvas');
            
            if (!this.appState.canvasElement) {
                setTimeout(() => this.findElements(), 100);
                return;
            }
            
            console.log('Canvas element found:', this.appState.canvasElement);
            console.log('Container:', this.appState.container);
            
            // Wait for container to be ready
            this.waitForContainer();
        }, 100);
    }

    waitForContainer() {
        if (this.appState.container) {
            console.log('Container is ready');
            if (this.onReady) {
                this.onReady();
            }
        } else {
            console.log('Waiting for container...');
            setTimeout(() => this.waitForContainer(), 50);
        }
    }
}
