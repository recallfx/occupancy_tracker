import { html, css, LitElement } from '../../lib.js';

/**
 * History controls component
 */
export class HistoryControls extends LitElement {
    static styles = css`
        :host {
            display: none;
        }

        :host([visible]) {
            display: block;
        }

        .history-controls {
            background: #1e1e1e;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px 20px;
            margin: 15px 20px;
            max-width: 960px;
            margin-left: auto;
            margin-right: auto;
        }

        .history-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .section-title {
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #b0b0b0;
            font-weight: bold;
        }

        .slider-container {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .icon-btn {
            background: transparent;
            border: 1px solid #333;
            color: #ffffff;
            cursor: pointer;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 14px;
            transition: all 0.2s;
        }

        .icon-btn:hover {
            border-color: #bb86fc;
            background: rgba(187, 134, 252, 0.1);
        }

        input[type="range"] {
            flex: 1;
            height: 8px;
            border-radius: 4px;
            outline: none;
            background: #333;
            -webkit-appearance: none;
        }

        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #bb86fc;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }

        input[type="range"]::-moz-range-thumb {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #bb86fc;
            cursor: pointer;
            border: none;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }

        .history-info {
            font-size: 0.85rem;
            color: #b0b0b0;
            min-width: 80px;
            text-align: right;
        }

        .history-timestamp {
            margin-top: 8px;
            font-size: 0.8rem;
            color: #b0b0b0;
            text-align: center;
        }

        .ghost-button {
            border: 1px solid #333;
            background: transparent;
            color: #ffffff;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: border-color 0.2s, color 0.2s;
        }

        .ghost-button:hover {
            border-color: #bb86fc;
            color: #bb86fc;
        }
    `;

    static properties = {
        visible: { type: Boolean, reflect: true },
        currentIndex: { type: Number },
        totalCount: { type: Number },
        timestamp: { type: String },
        isPlaying: { type: Boolean }
    };

    constructor() {
        super();
        this.visible = false;
        this.currentIndex = 0;
        this.totalCount = 0;
        this.timestamp = '';
        this.isPlaying = false;
    }

    render() {
        return html`
            <div class="history-controls">
                <div class="history-header">
                    <span class="section-title">📜 History Playback</span>
                    <button class="ghost-button" @click=${this._handleExit}>Exit Replay</button>
                </div>
                <div class="slider-container">
                    <button class="icon-btn" @click=${this._handleStepBack} title="Step Backward">◀️</button>
                    <button class="icon-btn" @click=${this._handlePlayPause} title="Play/Pause">
                        ${this.isPlaying ? '⏸️' : '▶️'}
                    </button>
                    <button class="icon-btn" @click=${this._handleStepForward} title="Step Forward">▶️▶️</button>
                    <input type="range" 
                           min="0" 
                           max=${this.totalCount - 1} 
                           .value=${String(this.currentIndex)}
                           @input=${this._handleSliderChange}>
                    <span class="history-info">${this.currentIndex + 1} / ${this.totalCount}</span>
                </div>
                <div class="history-timestamp">${this.timestamp}</div>
            </div>
        `;
    }

    _handleExit() {
        this.dispatchEvent(new CustomEvent('history-exit', { bubbles: true, composed: true }));
    }

    _handleStepBack() {
        this.dispatchEvent(new CustomEvent('history-step-back', { bubbles: true, composed: true }));
    }

    _handleStepForward() {
        this.dispatchEvent(new CustomEvent('history-step-forward', { bubbles: true, composed: true }));
    }

    _handlePlayPause() {
        this.dispatchEvent(new CustomEvent('history-play-pause', { bubbles: true, composed: true }));
    }

    _handleSliderChange(e) {
        this.dispatchEvent(new CustomEvent('history-seek', {
            detail: { index: parseInt(e.target.value) },
            bubbles: true,
            composed: true
        }));
    }
}

customElements.define('history-controls', HistoryControls);
