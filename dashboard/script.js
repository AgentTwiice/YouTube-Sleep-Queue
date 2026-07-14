class PlaylistDashboard {
    constructor() {
        this.currentPlaylist = [];
        this.apiBaseUrl = `${window.location.origin}/api`;
        this.csrfToken = null;
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.checkBackendAvailability();
    }

    setupEventListeners() {
        document.getElementById('file-input').addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (file) this.loadPlaylistFromFile(file);
        });
        document.getElementById('load-sample').addEventListener('click', () => {
            if (this.csrfToken) this.loadFromAPI(); else this.loadSampleData();
        });
        document.getElementById('clear-playlist').addEventListener('click', () => this.clearPlaylist());
    }

    setupDragAndDrop() {
        const dropZone = document.getElementById('drop-zone');
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((name) => {
            document.body.addEventListener(name, (event) => {
                event.preventDefault();
                event.stopPropagation();
            });
        });
        ['dragenter', 'dragover'].forEach((name) => document.body.addEventListener(name, () => dropZone.classList.add('drag-over')));
        ['dragleave', 'drop'].forEach((name) => document.body.addEventListener(name, () => dropZone.classList.remove('drag-over')));
        document.body.addEventListener('drop', (event) => {
            const file = event.dataTransfer.files[0];
            if (!file || (!file.name.toLowerCase().endsWith('.json') && file.type !== 'application/json')) {
                this.showError('Please drop a JSON file.');
                return;
            }
            this.loadPlaylistFromFile(file);
        });
    }

    async checkBackendAvailability() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/status`, {cache: 'no-store'});
            if (!response.ok) throw new Error('Backend unavailable');
            const tokenResponse = await fetch(`${this.apiBaseUrl}/csrf-token`, {cache: 'no-store'});
            if (!tokenResponse.ok) throw new Error('Request protection unavailable');
            this.csrfToken = (await tokenResponse.json()).csrf_token;
            document.getElementById('load-sample').textContent = 'Load from API';
            this.addRefreshButton();
            this.loadFromAPI();
        } catch (_error) {
            document.getElementById('load-sample').textContent = 'Load Demonstration Data';
        }
    }

    addRefreshButton() {
        if (document.getElementById('refresh-playlist')) return;
        const button = document.createElement('button');
        button.id = 'refresh-playlist';
        button.className = 'button-secondary';
        button.textContent = 'Refresh Playlist';
        button.addEventListener('click', () => this.refreshPlaylist(false));
        document.querySelector('.controls').appendChild(button);
    }

    async loadFromAPI() {
        try {
            this.showLoading('Loading playlist from API...');
            const response = await fetch(`${this.apiBaseUrl}/playlist`, {cache: 'no-store'});
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || `HTTP ${response.status}`);
            this.displayPlaylist(result.data);
            this.showDataSource(result.source, result.stale, result.last_updated);
        } catch (error) {
            this.showError(`Could not load playlist from API: ${error.message}`);
        } finally {
            this.hideLoading();
        }
    }

    async refreshPlaylist(dryRun) {
        const button = document.getElementById('refresh-playlist');
        button.disabled = true;
        button.textContent = 'Starting refresh...';
        try {
            const response = await fetch(`${this.apiBaseUrl}/refresh`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken},
                body: JSON.stringify({dry_run: dryRun})
            });
            const result = await response.json();
            if (response.status !== 202 || !result.success) throw new Error(result.error || `HTTP ${response.status}`);
            await this.pollRefresh(result.job_id, button);
        } catch (error) {
            this.showError(`Could not refresh playlist: ${error.message}`);
        } finally {
            button.disabled = false;
            button.textContent = 'Refresh Playlist';
        }
    }

    async pollRefresh(jobId, button) {
        while (true) {
            await new Promise((resolve) => setTimeout(resolve, 1000));
            const response = await fetch(`${this.apiBaseUrl}/refresh/${encodeURIComponent(jobId)}`, {cache: 'no-store'});
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || 'Could not read refresh status');
            button.textContent = `Refresh: ${result.job.progress}`;
            if (result.job.status === 'completed') {
                this.showSuccess('Playlist refresh completed.');
                await this.loadFromAPI();
                return;
            }
            if (['failed', 'timed_out', 'abandoned'].includes(result.job.status)) {
                throw new Error(result.job.error || `Refresh ${result.job.status}`);
            }
        }
    }

    async loadSampleData() {
        try {
            const response = await fetch('./playlist.example.json');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            this.displayPlaylist(await response.json());
            this.showDataSource('demonstration', true, null);
        } catch (error) {
            this.showError(`Could not load demonstration data: ${error.message}`);
        }
    }

    loadPlaylistFromFile(file) {
        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const value = JSON.parse(event.target.result);
                this.displayPlaylist(value);
                this.showDataSource('local file', true, null);
            } catch (_error) {
                this.showError('Invalid JSON file. Expected an array of videos.');
            }
        };
        reader.onerror = () => this.showError('Could not read the selected file.');
        reader.readAsText(file);
    }

    showDataSource(source, stale, updated) {
        let label = document.getElementById('data-source-status');
        if (!label) {
            label = document.createElement('p');
            label.id = 'data-source-status';
            document.getElementById('playlist-container').prepend(label);
        }
        const freshness = stale ? 'stale/demo' : 'current';
        label.textContent = `Data source: ${source || 'none'} (${freshness})${updated ? `; updated ${new Date(updated).toLocaleString()}` : ''}`;
    }

    displayPlaylist(videos) {
        if (!Array.isArray(videos)) {
            this.showError('Invalid playlist format. Expected an array of videos.');
            return;
        }
        this.currentPlaylist = videos;
        this.updateStats();
        this.renderVideoGrid();
        document.getElementById('playlist-container').style.display = 'block';
        document.getElementById('drop-zone').style.display = 'none';
        document.getElementById('playlist-stats').style.display = 'flex';
    }

    updateStats() {
        const seconds = this.currentPlaylist.reduce((sum, video) => sum + (Number(video.duration_seconds) || 0), 0);
        document.getElementById('video-count').textContent = String(this.currentPlaylist.length);
        document.getElementById('total-duration').textContent = this.formatDuration(seconds);
        document.getElementById('channel-count').textContent = String(new Set(this.currentPlaylist.map((video) => video.channel_id)).size);
    }

    renderVideoGrid() {
        const container = document.getElementById('video-grid');
        container.replaceChildren();
        this.currentPlaylist.forEach((video) => container.appendChild(this.createVideoCard(video)));
    }

    createVideoCard(video) {
        const id = /^[A-Za-z0-9_-]{11}$/.test(String(video.video_id || '')) ? video.video_id : null;
        const card = document.createElement('article');
        card.className = 'video-card';
        const thumbnail = document.createElement('div');
        thumbnail.className = 'video-thumbnail';
        const image = document.createElement('img');
        image.loading = 'lazy';
        image.alt = String(video.title || 'Untitled video');
        if (id) image.src = `https://i.ytimg.com/vi/${encodeURIComponent(id)}/mqdefault.jpg`;
        const duration = document.createElement('div');
        duration.className = 'video-duration';
        duration.textContent = this.formatDuration(Number(video.duration_seconds) || 0);
        thumbnail.append(image, duration);

        const info = document.createElement('div');
        info.className = 'video-info';
        const heading = document.createElement('h3');
        heading.className = 'video-title';
        const title = document.createElement('a');
        title.textContent = String(video.title || 'Untitled video');
        title.target = '_blank';
        title.rel = 'noopener noreferrer';
        title.href = id ? `https://www.youtube.com/watch?v=${encodeURIComponent(id)}` : '#';
        heading.appendChild(title);
        const channel = document.createElement('div');
        channel.className = 'channel-name';
        channel.textContent = String(video.channel_title || 'Unknown channel');
        const published = document.createElement('div');
        published.className = 'publish-date';
        published.textContent = this.formatDate(video.published_at);
        const status = document.createElement('span');
        status.className = `video-status ${video.added ? 'added' : 'not-added'}`;
        status.textContent = String(video.playlist_status || (video.added ? 'added' : 'not added'));
        info.append(heading, channel, published, status);
        card.append(thumbnail, info);
        return card;
    }

    formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const remaining = Math.floor(seconds % 60);
        return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}` : `${minutes}:${String(remaining).padStart(2, '0')}`;
    }

    formatDate(value) {
        if (!value) return 'Unknown date';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? 'Unknown date' : date.toLocaleDateString();
    }

    clearPlaylist() {
        this.currentPlaylist = [];
        document.getElementById('playlist-container').style.display = 'none';
        document.getElementById('playlist-stats').style.display = 'none';
        document.getElementById('drop-zone').style.display = 'flex';
        document.getElementById('file-input').value = '';
    }

    showError(message) {
        document.getElementById('error-text').textContent = String(message);
        document.getElementById('error-message').style.display = 'flex';
    }

    showLoading(message) {
        let overlay = document.getElementById('loading-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'loading-overlay';
            overlay.className = 'loading-overlay';
            const text = document.createElement('p');
            text.className = 'loading-text';
            overlay.appendChild(text);
            document.body.appendChild(overlay);
        }
        overlay.querySelector('.loading-text').textContent = String(message);
        overlay.style.display = 'flex';
    }

    hideLoading() {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    showSuccess(message) {
        let element = document.getElementById('success-message');
        if (!element) {
            element = document.createElement('div');
            element.id = 'success-message';
            element.className = 'success-message';
            document.querySelector('.container').appendChild(element);
        }
        element.textContent = String(message);
        element.style.display = 'flex';
        setTimeout(() => { element.style.display = 'none'; }, 3000);
    }
}

document.addEventListener('DOMContentLoaded', () => new PlaylistDashboard());
