// static/js/referral-tracking.js
// Enhanced referral tracking and automation

class ReferralTracker {
    constructor() {
        this.initializeTracking();
        this.setupRealTimeUpdates();
        this.setupAdvancedSharing();
    }

    initializeTracking() {
        // Track referral link clicks
        document.addEventListener('DOMContentLoaded', () => {
            // Track when someone visits with a referral code
            const urlParams = new URLSearchParams(window.location.search);
            const referralCode = urlParams.get('ref');

            if (referralCode) {
                this.trackReferralClick(referralCode);
                this.showReferralBanner(referralCode);
            }
        });
    }

    trackReferralClick(referralCode) {
        // Send tracking data to backend
        fetch('/api/track-referral/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': this.getCookie('csrftoken')
            },
            body: `referral_code=${referralCode}`
        }).catch(error => console.log('Tracking error:', error));
    }

    showReferralBanner(referralCode) {
        // Show a friendly banner for referred visitors
        const banner = document.createElement('div');
        banner.className = 'referral-banner bg-blue-500 text-white p-3 text-center';
        banner.innerHTML = `
            <div class="container mx-auto">
                <i class="fas fa-gift mr-2"></i>
                Welcome! You've been referred by someone awesome.
                <strong>Register now to start earning!</strong>
                <button onclick="this.parentElement.parentElement.style.display='none'" class="ml-4 text-white hover:text-gray-200">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
        document.body.insertBefore(banner, document.body.firstChild);
    }

    setupRealTimeUpdates() {
        // Update referral stats in real-time
        if (window.location.pathname.includes('/referrals/')) {
            setInterval(() => {
                this.updateReferralStats();
            }, 30000); // Update every 30 seconds
        }
    }

    async updateReferralStats() {
        try {
            const response = await fetch('/api/referral-stats/');
            const data = await response.json();

            // Update displayed stats
            this.updateStatCard('total-referrals', data.total_referrals);
            this.updateStatCard('total-earnings', `KSh ${data.total_earnings}`);
            this.updateStatCard('current-balance', `KSh ${data.current_balance}`);
            this.updateStatCard('pending-commissions', data.pending_commissions);

            // Show notification for new activity
            if (data.recent_activity.new_referrals > 0) {
                this.showNotification(
                    `${data.recent_activity.new_referrals} new referral(s)!`,
                    'success'
                );
            }
        } catch (error) {
            console.log('Stats update error:', error);
        }
    }

    updateStatCard(elementId, value) {
        const element = document.getElementById(elementId);
        if (element && element.textContent !== value.toString()) {
            element.textContent = value;
            element.classList.add('stat-updated');
            setTimeout(() => element.classList.remove('stat-updated'), 1000);
        }
    }

    setupAdvancedSharing() {
        // Add advanced sharing options
        this.addQRCodeSharing();
        this.addBulkSharing();
        this.addCustomMessages();
    }

    addQRCodeSharing() {
        // Generate QR code for referral link
        const qrButton = document.getElementById('generate-qr');
        if (qrButton) {
            qrButton.addEventListener('click', () => {
                const referralLink = document.getElementById('referralLink').value;
                this.generateQRCode(referralLink);
            });
        }
    }

    generateQRCode(url) {
        // Use QR code library (you'd need to include qrcode.js)
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
        modal.innerHTML = `
            <div class="bg-white p-6 rounded-lg max-w-sm mx-4">
                <h3 class="text-lg font-bold mb-4">Referral QR Code</h3>
                <div id="qrcode" class="text-center mb-4"></div>
                <p class="text-sm text-gray-600 mb-4">Share this QR code for easy mobile referrals!</p>
                <div class="flex space-x-2">
                    <button onclick="this.parentElement.parentElement.parentElement.remove()"
                            class="flex-1 bg-gray-500 text-white py-2 rounded">Close</button>
                    <button onclick="this.downloadQRCode()"
                            class="flex-1 bg-blue-500 text-white py-2 rounded">Download</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        // Generate QR code (requires qrcode.js library)
        // QRCode.toCanvas(document.getElementById('qrcode'), url);
    }

    addBulkSharing() {
        const bulkShareButton = document.getElementById('bulk-share');
        if (bulkShareButton) {
            bulkShareButton.addEventListener('click', () => {
                this.showBulkShareModal();
            });
        }
    }

    showBulkShareModal() {
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
        modal.innerHTML = `
            <div class="bg-white p-6 rounded-lg max-w-md mx-4">
                <h3 class="text-lg font-bold mb-4">Bulk Share Referral Link</h3>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium mb-2">Phone Numbers (one per line):</label>
                        <textarea id="phoneNumbers" rows="6" placeholder="254712345678\n254787654321"
                                  class="w-full border rounded p-2"></textarea>
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-2">Custom Message:</label>
                        <textarea id="customMessage" rows="3"
                                  placeholder="Hi! Join SurveyEarn and start earning money from surveys!"
                                  class="w-full border rounded p-2"></textarea>
                    </div>
                    <div class="flex space-x-2">
                        <button onclick="this.parentElement.parentElement.parentElement.remove()"
                                class="flex-1 bg-gray-500 text-white py-2 rounded">Cancel</button>
                        <button onclick="referralTracker.sendBulkMessages()"
                                class="flex-1 bg-green-500 text-white py-2 rounded">Send via WhatsApp</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    sendBulkMessages() {
        const phoneNumbers = document.getElementById('phoneNumbers').value.split('\n');
        const customMessage = document.getElementById('customMessage').value;
        const referralLink = document.getElementById('referralLink').value;

        phoneNumbers.forEach((phone, index) => {
            if (phone.trim()) {
                setTimeout(() => {
                    const message = customMessage || `Join SurveyEarn and start earning money from surveys!`;
                    const fullMessage = encodeURIComponent(`${message} ${referralLink}`);
                    window.open(`https://wa.me/${phone.trim()}?text=${fullMessage}`, '_blank');
                }, index * 1000); // Delay each message by 1 second
            }
        });

        // Close modal
        document.querySelector('.fixed.inset-0').remove();
        this.showNotification('WhatsApp messages queued!', 'success');
    }

    addCustomMessages() {
        // Add preset custom messages for different platforms
        const messages = {
            whatsapp: "🚀 Join SurveyEarn and start earning real money from surveys! I've been using it and it's amazing. Use my link to get started:",
            twitter: "💰 Found an awesome way to earn money online! Join SurveyEarn using my referral link:",
            facebook: "Hey friends! 💸 I've been earning extra cash with SurveyEarn. Join me and start making money from surveys:",
            sms: "Hi! Join SurveyEarn and earn money from surveys. Use my referral link:"
        };

        // Update share buttons with custom messages
        document.getElementById('share-whatsapp')?.addEventListener('click', () => {
            this.shareWithCustomMessage('whatsapp', messages.whatsapp);
        });

        document.getElementById('share-twitter')?.addEventListener('click', () => {
            this.shareWithCustomMessage('twitter', messages.twitter);
        });
    }

    shareWithCustomMessage(platform, message) {
        const referralLink = document.getElementById('referralLink').value;
        const fullMessage = encodeURIComponent(`${message} ${referralLink}`);

        const urls = {
            whatsapp: `https://wa.me/?text=${fullMessage}`,
            twitter: `https://twitter.com/intent/tweet?text=${fullMessage}`,
            facebook: `https://www.facebook.com/sharer/sharer.php?quote=${fullMessage}&u=${encodeURIComponent(referralLink)}`
        };

        if (urls[platform]) {
            window.open(urls[platform], '_blank');
        }
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        const bgColor = type === 'success' ? 'bg-green-500' : type === 'error' ? 'bg-red-500' : 'bg-blue-500';

        notification.className = `fixed top-4 right-4 ${bgColor} text-white px-6 py-3 rounded-lg shadow-lg transform translate-x-full transition-transform duration-300 z-50`;
        notification.innerHTML = `
            <div class="flex items-center">
                <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'} mr-2"></i>
                <span>${message}</span>
            </div>
        `;

        document.body.appendChild(notification);

        // Animate in
        setTimeout(() => notification.classList.remove('translate-x-full'), 100);

        // Animate out after 4 seconds
        setTimeout(() => {
            notification.classList.add('translate-x-full');
            setTimeout(() => notification.remove(), 300);
        }, 4000);
    }

    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

// Initialize the referral tracker
const referralTracker = new ReferralTracker();

// Add some CSS for animations
const style = document.createElement('style');
style.textContent = `
    .stat-updated {
        animation: highlight 1s ease-in-out;
    }

    @keyframes highlight {
        0%, 100% { background-color: transparent; }
        50% { background-color: #fef3cd; }
    }

    .referral-banner {
        animation: slideDown 0.5s ease-out;
    }

    @keyframes slideDown {
        from { transform: translateY(-100%); }
        to { transform: translateY(0