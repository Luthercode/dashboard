/**
 * db.js — IndexedDB + Sync Engine
 * Armazena dados localmente, sincroniza com servidor quando online.
 */
const DB_NAME = 'dashboard_fin';
const DB_VERSION = 2;

const OfflineDB = {
    db: null,

    async open() {
        if (this.db) return this.db;
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = e => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains('transactions')) {
                    db.createObjectStore('transactions', { keyPath: 'id' });
                }
                if (!db.objectStoreNames.contains('spreadsheets')) {
                    db.createObjectStore('spreadsheets', { keyPath: 'id' });
                }
                if (!db.objectStoreNames.contains('summary')) {
                    db.createObjectStore('summary', { keyPath: 'key' });
                }
                if (!db.objectStoreNames.contains('syncQueue')) {
                    const sq = db.createObjectStore('syncQueue', { keyPath: 'qid', autoIncrement: true });
                    sq.createIndex('timestamp', 'timestamp');
                }
            };
            req.onsuccess = e => { this.db = e.target.result; resolve(this.db); };
            req.onerror = () => reject(req.error);
        });
    },

    async _tx(store, mode) {
        const db = await this.open();
        return db.transaction(store, mode).objectStore(store);
    },

    async getAll(store) {
        const s = await this._tx(store, 'readonly');
        return new Promise((resolve, reject) => {
            const req = s.getAll();
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    },

    async get(store, id) {
        const s = await this._tx(store, 'readonly');
        return new Promise((resolve, reject) => {
            const req = s.get(id);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    },

    async put(store, item) {
        const s = await this._tx(store, 'readwrite');
        return new Promise((resolve, reject) => {
            const req = s.put(item);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    },

    async putAll(store, items) {
        const db = await this.open();
        const tx = db.transaction(store, 'readwrite');
        const s = tx.objectStore(store);
        items.forEach(item => s.put(item));
        return new Promise((resolve, reject) => {
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    },

    async del(store, id) {
        const s = await this._tx(store, 'readwrite');
        return new Promise((resolve, reject) => {
            const req = s.delete(id);
            req.onsuccess = () => resolve();
            req.onerror = () => reject(req.error);
        });
    },

    async clear(store) {
        const s = await this._tx(store, 'readwrite');
        return new Promise((resolve, reject) => {
            const req = s.clear();
            req.onsuccess = () => resolve();
            req.onerror = () => reject(req.error);
        });
    },

    // ── Sync Queue ──
    async addToSync(action) {
        // action: {type:'create'|'update'|'delete', store:'transactions'|'spreadsheets', data:{...}, endpoint:'/transactions'}
        action.timestamp = Date.now();
        action.status = 'pending';
        await this.put('syncQueue', action);
    },

    async getPendingSync() {
        return (await this.getAll('syncQueue')).filter(q => q.status === 'pending');
    },

    async clearSynced(qid) {
        await this.del('syncQueue', qid);
    },

    // ── Cache summary ──
    async saveSummary(periodo, data) {
        await this.put('summary', { key: 'summary_' + (periodo || 'all'), ...data, _cached: Date.now() });
    },

    async getSummary(periodo) {
        return this.get('summary', 'summary_' + (periodo || 'all'));
    },
};

// ── Sync Engine ──
const SyncEngine = {
    syncing: false,
    online: navigator.onLine,
    listeners: [],
    pendingCount: 0,

    retryTimer: null,

    init() {
        window.addEventListener('online', () => { this.online = true; this.notify(); this.processQueue(); });
        window.addEventListener('offline', () => { this.online = false; this.notify(); if(this.retryTimer){clearTimeout(this.retryTimer);this.retryTimer=null;} });
        // Listen for SW sync message
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.addEventListener('message', e => {
                if (e.data && e.data.type === 'SYNC_NOW') this.processQueue();
            });
        }
        this.updateCount();
        // Tentar sync ao iniciar (caso haja pendentes de sessão anterior)
        if (this.online) setTimeout(() => this.processQueue(), 2000);
    },

    onChange(fn) { this.listeners.push(fn); },

    notify() {
        this.listeners.forEach(fn => fn({ online: this.online, syncing: this.syncing, pending: this.pendingCount }));
    },

    async updateCount() {
        const q = await OfflineDB.getPendingSync();
        this.pendingCount = q.length;
        this.notify();
    },

    async queueAction(action) {
        await OfflineDB.addToSync(action);
        await this.updateCount();
        if (this.online) this.processQueue();
    },

    async processQueue() {
        if (this.syncing || !this.online) return;
        this.syncing = true;
        this.notify();
        const TOKEN = localStorage.getItem('access_token');
        if (!TOKEN) { this.syncing = false; return; }
        const headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN };
        const queue = await OfflineDB.getPendingSync();

        for (const item of queue) {
            try {
                let url = APP_CONFIG.API_URL + item.endpoint;
                let opts = { headers };

                if (item.type === 'create') {
                    opts.method = 'POST';
                    opts.body = JSON.stringify(item.data);
                } else if (item.type === 'update') {
                    opts.method = 'PUT';
                    opts.body = JSON.stringify(item.data);
                } else if (item.type === 'delete') {
                    opts.method = 'DELETE';
                }

                const resp = await fetch(url, opts);
                if (resp.ok) {
                    await OfflineDB.clearSynced(item.qid);
                    // If created, update local ID with server ID
                    if (item.type === 'create') {
                        const serverData = await resp.json();
                        if (item.localId && serverData.id) {
                            await OfflineDB.del(item.store, item.localId);
                            await OfflineDB.put(item.store, serverData);
                        }
                    }
                }
            } catch (e) {
                console.log('Sync failed for item:', item.qid, e);
                break; // Stop on first failure, retry below
            }
        }

        this.syncing = false;
        await this.updateCount();

        // Retry automático se ainda houver pendentes
        if (this.pendingCount > 0 && this.online) {
            if (this.retryTimer) clearTimeout(this.retryTimer);
            this.retryTimer = setTimeout(() => { this.retryTimer = null; this.processQueue(); }, 10000);
        }
    }
};
