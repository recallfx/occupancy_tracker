/**
 * API utilities for simulation
 */

import { showToast } from './utils.js';

export async function verifyHistory() {
    try {
        const response = await fetch('/api/verify_history', { method: 'POST' });
        const result = await response.json();
        
        if (result.passed) {
            console.log('✅ History verification passed');
            showToast('History verification passed', 'success');
        } else {
            console.error('❌ History verification failed - check server logs');
            showToast('History verification failed - check logs', 'error');
        }
        
        return result;
    } catch (err) {
        console.error('Error verifying history:', err);
        showToast('Error verifying history', 'error');
        throw err;
    }
}
