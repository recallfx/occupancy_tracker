/**
 * Application state management
 */

const DEFAULT_DIMENSIONS = { width: 600, height: 500 };

export class AppState {
    constructor() {
        // Layout data
        this.layout = {
            areas: [],
            sensors: [],
            connections: [],
            dimensions: { ...DEFAULT_DIMENSIONS }
        };
        
        // Coordinator state
        this.state = {
            areas: {},
            sensors: {},
            warnings: [],
            history_count: 0
        };
        
        // Simulation-specific state
        this.persons = [
            { id: 1, x: 50, y: 50, dragging: false, radius: 15 },
            { id: 2, x: 100, y: 50, dragging: false, radius: 15 },
            { id: 3, x: 150, y: 50, dragging: false, radius: 15 }
        ];
        
        this.activeSensors = new Set();
        
        // References (set externally)
        this.ws = null;
        this.inputSystem = null;
        this.historyPlayer = null;
        this.appElement = null;
        this.historyControlsElement = null;
        this.canvasElement = null;
    }

    get container() {
        return this.canvasElement?.shadowRoot?.querySelector('#sim-container');
    }

    updateLayout(newLayout) {
        this.layout.areas = newLayout.areas || [];
        this.layout.sensors = newLayout.sensors || [];
        this.layout.connections = newLayout.connections || [];
        this.layout.dimensions = newLayout.dimensions || this.layout.dimensions || { ...DEFAULT_DIMENSIONS };
    }

    updateState(newState) {
        this.state = newState;
        if (newState.history_count !== undefined) {
            this.state.history_count = newState.history_count;
        }
    }

    updateUI() {
        if (this.appElement) {
            this.appElement.connectionStatus = this.ws?.readyState === WebSocket.OPEN ? 'connected' : 'disconnected';
            this.appElement.historyCount = this.state.history_count || 0;
            this.appElement.hasWarnings = Array.isArray(this.state.warnings) && this.state.warnings.length > 0;
            this.appElement.canSend = this.ws?.readyState === WebSocket.OPEN;
        }
    }
}
