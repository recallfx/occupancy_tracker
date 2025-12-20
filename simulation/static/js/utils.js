import './components/toast.js';

export function formatTime(seconds) {
    if (seconds === null || seconds === undefined) return 'Never';
    if (seconds < 60) return Math.floor(seconds) + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    return '> 1h ago';
}

/**
 * Global toast helper function
 */
let toastElement = null;

export function showToast(message, type = 'info', duration = 3000) {
    if (!toastElement) {
        toastElement = document.createElement('toast-notification');
        document.body.appendChild(toastElement);
    }
    toastElement.show(message, type, duration);
}
