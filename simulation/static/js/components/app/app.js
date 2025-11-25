import { html, css, LitElement } from '../../lib.js';

/**
 * Main app container component
 */
export class OccupancySimApp extends LitElement {
    static styles = css`
        :host {
            display: flex;
            flex-direction: column;
            height: 100vh;
            background: #121212;
            color: #ffffff;
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }

        header {
            background-color: #1e1e1e;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            padding: 0 20px;
            justify-content: space-between;
            min-height: 60px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 15px;
            flex-shrink: 0;
        }

        .header-left h1 {
            font-size: 1.2rem;
            margin: 0;
            font-weight: 500;
            color: #bb86fc;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }

        main {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .ghost-button {
            border: 1px solid #333;
            background: transparent;
            color: #ffffff;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: border-color 0.2s, color 0.2s;
        }

        .ghost-button:hover:not(:disabled) {
            border-color: #bb86fc;
            color: #bb86fc;
        }

        .ghost-button:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }

        select {
            padding: 8px;
            border-radius: 4px;
            border: 1px solid #333;
            background: #2c2c2c;
            color: #ffffff;
            font-size: 0.85rem;
        }

        .status-badge {
            font-size: 0.8rem;
            padding: 4px 8px;
            border-radius: 4px;
            background: #333;
        }

        .status-badge.connected {
            color: #03dac6;
        }

        .status-badge.disconnected {
            color: #cf6679;
        }

        @media (max-width: 900px) {
            header {
                flex-wrap: wrap;
                gap: 10px;
            }
        }

        @media (max-width: 600px) {
            header {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
        }
    `;

    static properties = {
        connectionStatus: { type: String },
        historyCount: { type: Number },
        hasWarnings: { type: Boolean },
        canSend: { type: Boolean }
    };

    constructor() {
        super();
        this.connectionStatus = 'connecting';
        this.historyCount = 0;
        this.hasWarnings = false;
        this.canSend = false;
    }

    render() {
        return html`
            <header>
                <div class="header-left">
                    <h1>Occupancy Tracker Simulation</h1>
                </div>
                <div class="header-right">
                    <select @change=${this._handleScenarioChange}>
                        <option value="">Select Scenario...</option>
                        <option value="scenario1">Scenario 1: Bedroom Loop</option>
                        <option value="scenario2">Scenario 2: Bathroom Stay</option>
                    </select>
                    <button class="ghost-button" 
                            ?disabled=${this.historyCount === 0 || !this.canSend}
                            @click=${this._handleHistoryClick}>
                        📜 History (${this.historyCount})
                    </button>
                    <button class="ghost-button"
                            ?disabled=${this.historyCount === 0 || !this.canSend}
                            @click=${this._handleVerifyClick}>
                        ✓ Verify History
                    </button>
                    <button class="ghost-button"
                            ?disabled=${!this.hasWarnings || !this.canSend}
                            @click=${this._handleResetWarnings}>
                        Reset Warnings
                    </button>
                    <div class="status-badge ${this.connectionStatus}">
                        ${this._getStatusText()}
                    </div>
                </div>
            </header>
            <main>
                <sim-legend></sim-legend>
                <history-controls></history-controls>
                <sim-canvas></sim-canvas>
            </main>
        `;
    }

    _getStatusText() {
        return this.connectionStatus === 'connected' ? 'Connected' :
               this.connectionStatus === 'disconnected' ? 'Disconnected' : 'Connecting...';
    }

    _handleScenarioChange(e) {
        const event = new CustomEvent('scenario-selected', {
            detail: { scenario: e.target.value },
            bubbles: true,
            composed: true
        });
        this.dispatchEvent(event);
        e.target.value = '';
    }

    _handleHistoryClick() {
        this.dispatchEvent(new CustomEvent('history-open', { bubbles: true, composed: true }));
    }

    _handleVerifyClick() {
        this.dispatchEvent(new CustomEvent('verify-history', { bubbles: true, composed: true }));
    }

    _handleResetWarnings() {
        this.dispatchEvent(new CustomEvent('reset-warnings', { bubbles: true, composed: true }));
    }
}

customElements.define('occupancy-sim-app', OccupancySimApp);
