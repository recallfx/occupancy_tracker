import { html, css, LitElement } from '../lib.js';

/**
 * Legend component
 */
export class SimLegend extends LitElement {
    static styles = css`
        .legend {
            display: flex;
            gap: 15px;
            justify-content: center;
            padding: 15px 20px;
            background: #1e1e1e;
            border-bottom: 1px solid #333;
            flex-wrap: wrap;
            color: #b0b0b0;
            font-size: 0.85rem;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        @media (max-width: 600px) {
            .legend {
                flex-wrap: wrap;
                row-gap: 8px;
            }
        }
    `;

    render() {
        return html`
            <div class="legend">
                <div class="legend-item">
                    <div class="dot" style="background: blue"></div>
                    <span>Motion Sensor</span>
                </div>
                <div class="legend-item">
                    <div class="dot" style="background: green"></div>
                    <span>Magnetic Sensor</span>
                </div>
                <div class="legend-item">
                    <div class="dot" style="background: purple"></div>
                    <span>Camera Sensor</span>
                </div>
                <div class="legend-item">
                    <div class="dot" style="background: yellow; border: 2px solid blue;"></div>
                    <span>Active</span>
                </div>
                <div class="legend-item">
                    <div class="dot" style="background: white; border: 2px solid orange;"></div>
                    <span>Cooldown</span>
                </div>
                <div class="legend-item">
                    <div class="dot" style="background: red"></div>
                    <span>Person (Click or Drag)</span>
                </div>
            </div>
        `;
    }
}

customElements.define('sim-legend', SimLegend);
