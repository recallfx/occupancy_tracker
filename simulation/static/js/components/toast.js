import { html, css, LitElement } from '../lib.js';

/**
 * Toast notification component
 */
export class ToastNotification extends LitElement {
    static styles = css`
        :host {
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
        }

        .toast {
            padding: 12px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            font-family: 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            max-width: 300px;
            pointer-events: all;
            display: flex;
            align-items: center;
            gap: 10px;
            color: white;
            animation: slideIn 0.3s ease-out;
        }

        .toast.success {
            background: #10b981;
        }

        .toast.error {
            background: #ef4444;
        }

        .toast.warning {
            background: #f59e0b;
        }

        .toast.info {
            background: #3b82f6;
        }

        .toast.removing {
            animation: slideOut 0.3s ease-in;
        }

        .toast-icon {
            font-weight: bold;
            font-size: 16px;
        }

        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(400px);
                opacity: 0;
            }
        }
    `;

    static properties = {
        toasts: { type: Array, state: true }
    };

    constructor() {
        super();
        this.toasts = [];
        this.nextId = 0;
    }

    show(message, type = 'info', duration = 3000) {
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        const id = this.nextId++;
        const toast = {
            id,
            message,
            type,
            icon: icons[type] || icons.info,
            removing: false
        };

        this.toasts = [...this.toasts, toast];

        // Auto-remove after duration
        setTimeout(() => {
            this._removeToast(id);
        }, duration);
    }

    _removeToast(id) {
        // Mark as removing to trigger exit animation
        this.toasts = this.toasts.map(t => 
            t.id === id ? { ...t, removing: true } : t
        );

        // Actually remove after animation completes
        setTimeout(() => {
            this.toasts = this.toasts.filter(t => t.id !== id);
        }, 300);
    }

    render() {
        return html`
            ${this.toasts.map(toast => html`
                <div class="toast ${toast.type} ${toast.removing ? 'removing' : ''}">
                    <span class="toast-icon">${toast.icon}</span>
                    <span>${toast.message}</span>
                </div>
            `)}
        `;
    }
}

customElements.define('toast-notification', ToastNotification);
