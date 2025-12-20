import { html, css, LitElement } from '../../lib.js';

/**
 * Canvas container component
 */
export class SimCanvas extends LitElement {
    static styles = css`
        :host {
            flex: 1;
            display: flex;
            padding: 20px;
            overflow: auto;
            background: #121212;
        }

        .canvas-container {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            background: white;
            border-radius: 8px;
            padding: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            max-width: 960px;
            margin: 0 auto;
        }

        #sim-container {
            width: 100%;
            height: 100%;
        }

        @media (max-width: 600px) {
            :host {
                padding: 15px;
            }
        }
    `;

    firstUpdated() {
        // Notify that the canvas is ready
        this.dispatchEvent(new CustomEvent('canvas-ready', { 
            bubbles: true, 
            composed: true 
        }));
    }

    render() {
        return html`
            <div class="canvas-container">
                <div id="sim-container"></div>
            </div>
        `;
    }
}

customElements.define('sim-canvas', SimCanvas);
