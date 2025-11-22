export function formatTime(seconds) {
    if (seconds === null || seconds === undefined) return 'Never';
    if (seconds < 60) return Math.floor(seconds) + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    return '> 1h ago';
}
